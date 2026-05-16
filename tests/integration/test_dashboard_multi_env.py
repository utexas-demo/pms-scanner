"""Multi-env dashboard contract — T045 (/status) + T047 (SSE) (US5).

/status must match contracts/dashboard-events.md: top-level ``machine``,
an ``ntp`` block, and ``environments`` keyed by name with per-env
``current_run``/``last_run``. Every SSE event carries ``env`` +
``machine``; a ``clock_sync`` event is emitted after an NTP cycle.
"""
import asyncio
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient


def _settings(tmp_path: Path):
    p = tmp_path / "p"
    s = tmp_path / "s"
    p.mkdir()
    s.mkdir()
    env = {
        "MACHINE_IDENTITY": "macmini",
        "NTP__STARTUP_REQUIRED": "false",
        "ENVIRONMENTS": "production,staging",
        "ENV_PRODUCTION__WATCH_DIR": str(p),
        "ENV_PRODUCTION__BACKEND_BASE_URL": "https://adg.mpsinc.io",
        "ENV_PRODUCTION__API_TOKEN": "pt",
        "ENV_PRODUCTION__SCHEDULE_OFFSET_SECONDS": "0",
        "ENV_STAGING__WATCH_DIR": str(s),
        "ENV_STAGING__BACKEND_BASE_URL": "https://dev.adg.mpsinc.io",
        "ENV_STAGING__API_TOKEN": "st",
        "ENV_STAGING__SCHEDULE_OFFSET_SECONDS": "15",
    }
    from config import load_settings

    with patch.dict(os.environ, env, clear=True):
        return load_settings(dotenv=False)


@pytest_asyncio.fixture()
async def configured(tmp_path: Path):
    import dashboard
    from state import BatchRunState

    settings = _settings(tmp_path)
    state = BatchRunState(settings.machine, [e.name for e in settings.environments])
    dashboard.configure(settings, state)
    try:
        async with AsyncClient(
            transport=ASGITransport(app=dashboard.app), base_url="http://test"
        ) as ac:
            yield ac, settings, state, dashboard
    finally:
        dashboard._settings = None
        dashboard._run_state = None
        # Restore the shared AppState so loop/queue rebinding here does not
        # leak a dead-loop queue into legacy (unconfigured) SSE tests.
        dashboard._app_state.loop = None
        dashboard._app_state.event_queue = asyncio.Queue()


@pytest.mark.asyncio
async def test_status_shape(configured) -> None:
    client, settings, state, _dash = configured
    from ntp import ClockSyncEvent

    state.record_clock_sync(
        ClockSyncEvent(datetime.now(UTC), "pool.ntp.org", 0.043, "ok")
    )
    state.add_pages_uploaded("production", 2)
    state.set_current("production", current_file="scan.pdf", current_page=2,
                      total_pages=3)

    body = (await client.get("/status")).json()

    assert body["machine"] == "macmini"
    ntp = body["ntp"]
    assert ntp["source"] == "pool.ntp.org"
    assert ntp["offset_seconds"] == pytest.approx(0.043)
    assert ntp["outcome"] == "ok"
    assert "last_drift_warning" in ntp

    envs = body["environments"]
    assert set(envs) == {"production", "staging"}
    prod = envs["production"]
    assert prod["enabled"] is True
    assert prod["schedule_offset_seconds"] == 0
    assert prod["backend_base_url"] == "https://adg.mpsinc.io"
    assert "current_run" in prod and "last_run" in prod
    assert envs["staging"]["backend_base_url"] == "https://dev.adg.mpsinc.io"
    assert envs["staging"]["schedule_offset_seconds"] == 15


@pytest.mark.asyncio
async def test_sse_events_tagged(configured) -> None:
    """Every run/page/file SSE event carries env+machine; clock_sync arrives.

    Uses a raw ASGI drive (httpx buffers infinite SSE streams). Events are
    queued on THIS running loop's queue first; emit_clock_event is exercised
    for the clock_sync path.
    """
    _client, _settings, _state, dash = configured
    dash._app_state.loop = asyncio.get_running_loop()
    dash._app_state.event_queue = asyncio.Queue()

    for et in ("run_started", "page_done", "file_done", "run_done"):
        await dash._app_state.event_queue.put(
            {"type": et, "env": "production", "machine": "macmini"}
        )
    dash.emit_clock_event(
        {
            "type": "clock_sync",
            "machine": "macmini",
            "source": "pool.ntp.org",
            "offset_seconds": 0.01,
            "outcome": "ok",
        }
    )

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "path": "/events",
        "query_string": b"",
        "root_path": "",
        "headers": [],
    }
    body = bytearray()

    async def receive() -> dict:
        await asyncio.sleep(0.6)
        return {"type": "http.disconnect"}

    async def send(message: dict) -> None:
        if message["type"] == "http.response.body":
            body.extend(message.get("body", b""))

    try:
        await asyncio.wait_for(dash.app(scope, receive, send), timeout=3.0)
    except (TimeoutError, asyncio.CancelledError):
        pass

    events: list[dict] = []
    for frame in body.decode().split("\n\n"):
        for line in frame.splitlines():
            if line.startswith("data:"):
                try:
                    ev = json.loads(line[5:].strip())
                except json.JSONDecodeError:
                    continue
                if ev:
                    events.append(ev)

    tagged = {
        e["type"]: e
        for e in events
        if e.get("type")
        in {"run_started", "page_done", "file_done", "run_done"}
    }
    assert set(tagged) == {"run_started", "page_done", "file_done", "run_done"}
    for et, ev in tagged.items():
        assert ev["env"] == "production", et
        assert ev["machine"] == "macmini", et
    assert any(e.get("type") == "clock_sync" for e in events)
