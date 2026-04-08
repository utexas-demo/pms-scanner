"""Unit tests for scanner/api.py — TDD: must FAIL before implementation."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from httpx import ASGITransport, AsyncClient

from scanner.store import FileRecord, Status, StatusStore

# ---------------------------------------------------------------------------
# T007: FastAPI route tests (US1)
# ---------------------------------------------------------------------------


@pytest.fixture()
def clean_store(monkeypatch: pytest.MonkeyPatch) -> StatusStore:
    """Provide a fresh StatusStore and patch it into the api module."""
    store = StatusStore()
    monkeypatch.setattr("scanner.api.status_store", store)
    return store


@pytest.fixture()
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.anyio()
async def test_root_returns_html(clean_store: StatusStore) -> None:
    from scanner.api import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]


@pytest.mark.anyio()
async def test_health_returns_ok(clean_store: StatusStore) -> None:
    from scanner.api import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


@pytest.mark.anyio()
async def test_api_files_empty(clean_store: StatusStore) -> None:
    from scanner.api import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/files")
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.anyio()
async def test_api_files_returns_existing_records(clean_store: StatusStore) -> None:
    from scanner.api import app

    now = datetime.now(UTC)
    clean_store.add(
        FileRecord(
            id="r1",
            filename="img.jpg",
            status=Status.SUCCESS,
            detected_at=now,
            updated_at=now,
            error_message=None,
            attempts=1,
        )
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/files")
    data = resp.json()
    assert len(data) == 1
    assert data[0]["id"] == "r1"
    assert data[0]["status"] == "success"


@pytest.mark.anyio()
async def test_api_events_content_type(clean_store: StatusStore) -> None:
    import asyncio

    from scanner.api import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        try:
            async with asyncio.timeout(2):
                async with client.stream("GET", "/api/events") as resp:
                    assert resp.status_code == 200
                    ct = resp.headers.get("content-type", "")
                    assert "text/event-stream" in ct
        except TimeoutError:
            pass  # Expected — SSE stream is infinite


# ---------------------------------------------------------------------------
# T013: Session history (US2)
# ---------------------------------------------------------------------------


@pytest.mark.anyio()
async def test_api_files_includes_all_statuses(clean_store: StatusStore) -> None:
    """GET /api/files must return records in all states — nothing is purged."""
    from scanner.api import app

    now = datetime.now(UTC)
    clean_store.add(
        FileRecord(
            id="r1",
            filename="a.jpg",
            status=Status.PENDING,
            detected_at=now,
            updated_at=now,
            error_message=None,
            attempts=0,
        )
    )
    clean_store.add(
        FileRecord(
            id="r2",
            filename="b.jpg",
            status=Status.SUCCESS,
            detected_at=now,
            updated_at=now,
            error_message=None,
            attempts=1,
        )
    )
    clean_store.add(
        FileRecord(
            id="r3",
            filename="c.jpg",
            status=Status.FAILED,
            detected_at=now,
            updated_at=now,
            error_message="HTTP 503",
            attempts=3,
        )
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/files")
    data = resp.json()
    assert len(data) == 3
    statuses = {d["status"] for d in data}
    assert statuses == {"pending", "success", "failed"}


# ---------------------------------------------------------------------------
# T015: Failed upload visibility (US3) — API side
# ---------------------------------------------------------------------------


@pytest.mark.anyio()
async def test_api_files_failed_has_error_message(clean_store: StatusStore) -> None:
    """Failed records returned by /api/files must include non-null error_message."""
    from scanner.api import app

    now = datetime.now(UTC)
    clean_store.add(
        FileRecord(
            id="r1",
            filename="a.jpg",
            status=Status.FAILED,
            detected_at=now,
            updated_at=now,
            error_message="HTTP 401 — will not retry",
            attempts=1,
        )
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/files")
    data = resp.json()
    assert data[0]["error_message"] is not None
    assert "401" in data[0]["error_message"]
