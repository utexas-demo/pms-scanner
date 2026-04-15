"""
Integration tests for the FastAPI dashboard — T021.

Uses httpx.AsyncClient against the FastAPI app object directly (no running server needed).
"""

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient


@pytest.fixture(autouse=True)
def patch_env(monkeypatch):
    monkeypatch.setenv("BACKEND_BASE_URL", "http://x")
    monkeypatch.setenv("API_TOKEN", "t")


@pytest_asyncio.fixture()
async def client():
    """Async test client for the dashboard FastAPI app."""
    from dashboard import app

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac


@pytest.mark.asyncio
async def test_get_root_returns_html(client: AsyncClient):
    """GET / returns HTTP 200 with text/html content."""
    response = await client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers.get("content-type", "")


@pytest.mark.asyncio
async def test_get_status_json_shape(client: AsyncClient):
    """GET /status returns JSON with current_run and last_run keys."""
    response = await client.get("/status")
    assert response.status_code == 200
    body = response.json()
    assert "current_run" in body
    assert "last_run" in body


@pytest.mark.asyncio
async def test_get_healthz(client: AsyncClient):
    """GET /healthz returns {"status": "ok"}."""
    response = await client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_post_run_returns_202(client: AsyncClient):
    """POST /run returns 202 with run_id."""
    from unittest.mock import patch

    with patch("dashboard.threading.Thread") as mock_thread_cls:
        mock_thread = mock_thread_cls.return_value
        mock_thread.start.return_value = None
        response = await client.post("/run")

    assert response.status_code == 202
    body = response.json()
    assert "run_id" in body


@pytest.mark.asyncio
async def test_get_events_returns_event_stream():
    """
    GET /events ASGI response starts with HTTP 200 and text/event-stream.

    Uses a raw ASGI call with a short timeout because httpx's ASGI transport
    buffers the full response body (SSE streams never end, so streaming via
    httpx would hang).  We cancel after the response-start message is received.
    """
    import asyncio

    import dashboard

    # Pre-populate the queue so the generator yields immediately.
    await dashboard._app_state.event_queue.put({"type": "heartbeat"})

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

    response_start: dict = {}
    body_chunks: list[bytes] = []

    async def receive() -> dict:
        # Simulate disconnect after a brief pause so the generator can send headers
        await asyncio.sleep(0.5)
        return {"type": "http.disconnect"}

    async def send(message: dict) -> None:
        if message["type"] == "http.response.start":
            response_start.update(message)
        elif message["type"] == "http.response.body":
            body_chunks.append(message.get("body", b""))

    try:
        await asyncio.wait_for(dashboard.app(scope, receive, send), timeout=2.0)
    except (TimeoutError, asyncio.CancelledError):
        pass  # Expected — SSE stream is intentionally infinite

    assert response_start.get("status") == 200
    headers_dict = {k.lower(): v for k, v in response_start.get("headers", [])}
    content_type = headers_dict.get(b"content-type", b"").decode()
    assert "text/event-stream" in content_type
