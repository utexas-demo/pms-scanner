"""
FastAPI application for the upload progress dashboard.

Serves a single-page HTML dashboard at ``GET /`` with real-time status updates
via Server-Sent Events at ``GET /api/events``.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from sse_starlette.sse import EventSourceResponse
from starlette.requests import Request

from scanner.store import status_store

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    status_store.set_loop(asyncio.get_event_loop())
    yield


app = FastAPI(title="pms-scanner dashboard", lifespan=lifespan)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@app.get("/", response_class=HTMLResponse)
async def dashboard() -> HTMLResponse:
    """Serve the upload progress dashboard."""
    return HTMLResponse(DASHBOARD_HTML)


@app.get("/health")
async def health() -> dict[str, str]:
    """Readiness / liveness probe."""
    return {"status": "ok"}


@app.get("/api/files")
async def list_files() -> list[dict[str, Any]]:
    """Return a snapshot of all tracked file records."""
    return [r.to_dict() for r in status_store.all()]


@app.get("/api/events")
async def event_stream(request: Request) -> EventSourceResponse:
    """SSE endpoint — pushes a JSON event on every status change."""

    async def _generate() -> Any:
        q = status_store.subscribe()
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    payload = await asyncio.wait_for(q.get(), timeout=15.0)
                    yield {"data": payload}
                except TimeoutError:
                    yield {"comment": "heartbeat"}
        finally:
            status_store.unsubscribe(q)
            logger.debug("SSE client disconnected")

    return EventSourceResponse(_generate())


# ---------------------------------------------------------------------------
# Embedded dashboard HTML
# ---------------------------------------------------------------------------

DASHBOARD_HTML = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>pms-scanner — Upload Progress</title>
<style>
  :root { --bg: #f8f9fa; --card: #fff; --border: #dee2e6; --green: #28a745;
          --red: #dc3545; --blue: #007bff; --gray: #6c757d; }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto,
         sans-serif; background: var(--bg); color: #212529; padding: 1.5rem; }
  h1 { font-size: 1.4rem; margin-bottom: 1rem; }
  .status-bar { font-size: .85rem; color: var(--gray); margin-bottom: 1rem; }
  .status-bar .dot { display: inline-block; width: 8px; height: 8px;
    border-radius: 50%; margin-right: 4px; vertical-align: middle; }
  .dot.connected { background: var(--green); }
  .dot.disconnected { background: var(--red); }
  table { width: 100%; border-collapse: collapse; background: var(--card);
          border: 1px solid var(--border); border-radius: 6px;
          overflow: hidden; }
  th, td { padding: .6rem .8rem; text-align: left; border-bottom: 1px solid
           var(--border); font-size: .9rem; }
  th { background: #e9ecef; font-weight: 600; }
  .badge { display: inline-block; padding: 2px 8px; border-radius: 4px;
           font-size: .8rem; font-weight: 600; color: #fff; }
  .badge-pending  { background: var(--blue); }
  .badge-uploading { background: #fd7e14; }
  .badge-success  { background: var(--green); }
  .badge-failed   { background: var(--red); }
  .progress-bar { width: 120px; height: 8px; background: #e9ecef;
                  border-radius: 4px; overflow: hidden; }
  .progress-bar .fill { height: 100%; border-radius: 4px;
                        transition: width .3s ease; }
  .fill-pending   { width: 10%;  background: var(--blue); }
  .fill-uploading { width: 60%;  background: #fd7e14; }
  .fill-success   { width: 100%; background: var(--green); }
  .fill-failed    { width: 100%; background: var(--red); }
  .empty { text-align: center; padding: 2rem; color: var(--gray); }
  .error-msg { color: var(--red); font-size: .82rem; }
</style>
</head>
<body>
<h1>Upload Progress Dashboard</h1>
<div class="status-bar">
  <span class="dot disconnected" id="dot"></span>
  <span id="conn-status">Connecting…</span>
</div>

<table>
  <thead>
    <tr>
      <th>File</th><th>Status</th><th>Progress</th>
      <th>Attempts</th><th>Time</th><th>Error</th>
    </tr>
  </thead>
  <tbody id="tbody">
    <tr class="empty-row"><td colspan="6" class="empty">No files in queue.</td></tr>
  </tbody>
</table>

<script>
const tbody = document.getElementById('tbody');
const dot = document.getElementById('dot');
const connStatus = document.getElementById('conn-status');
const records = {};

function render() {
  const ids = Object.keys(records);
  if (ids.length === 0) {
    tbody.innerHTML = '<tr class="empty-row"><td colspan="6" class="empty">'
      + 'No files in queue.</td></tr>';
    return;
  }
  const rows = ids.map(id => {
    const r = records[id];
    const badge = `<span class="badge badge-${r.status}">${r.status}</span>`;
    const fill = `<div class="progress-bar"><div class="fill fill-${r.status}"></div></div>`;
    const ts = new Date(r.updated_at).toLocaleTimeString();
    const err = r.error_message
      ? `<span class="error-msg">${esc(r.error_message)}</span>` : '\\u2014';
    return `<tr><td>${esc(r.filename)}</td><td>${badge}</td><td>${fill}</td>`
      + `<td>${r.attempts}</td><td>${ts}</td><td>${err}</td></tr>`;
  });
  tbody.innerHTML = rows.join('');
}

function esc(s) {
  const d = document.createElement('div');
  d.textContent = s;
  return d.innerHTML;
}

// Bootstrap from REST snapshot
fetch('/api/files').then(r => r.json()).then(data => {
  data.forEach(r => { records[r.id] = r; });
  render();
});

// SSE live updates
const es = new EventSource('/api/events');
es.onopen = () => {
  dot.className = 'dot connected';
  connStatus.textContent = 'Connected';
};
es.onmessage = (e) => {
  const r = JSON.parse(e.data);
  records[r.id] = r;
  render();
};
es.onerror = () => {
  dot.className = 'dot disconnected';
  connStatus.textContent = 'Reconnecting\\u2026';
};
</script>
</body>
</html>
"""
