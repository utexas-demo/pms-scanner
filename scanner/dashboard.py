"""
FastAPI dashboard for real-time batch progress.

Endpoints
---------
GET  /         Inline single-page HTML dashboard
GET  /status   JSON snapshot of current and last batch run
GET  /events   Server-Sent Events stream (run/file/page events + heartbeats)
POST /run      Manually trigger a batch run immediately
GET  /healthz  Health check
"""

import asyncio
import json
import logging
import threading
import uuid
from collections.abc import AsyncGenerator

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from state import AppState
from state import app_state as _default_app_state

logger = logging.getLogger(__name__)

app = FastAPI(title="pms-scanner dashboard")

# ---------------------------------------------------------------------------
# State injection — tests can replace this
# ---------------------------------------------------------------------------

_app_state: AppState = _default_app_state

# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@app.get("/", response_class=HTMLResponse)
async def index() -> HTMLResponse:
    """Serve the dashboard HTML page."""
    return HTMLResponse(content=_DASHBOARD_HTML, status_code=200)


@app.get("/status")
async def status() -> JSONResponse:
    """Return a JSON snapshot of the current and last run."""
    return JSONResponse(_app_state.to_status_dict())


@app.get("/events")
async def events() -> StreamingResponse:
    """
    Server-Sent Events stream.

    Sends queued events from AppState.event_queue plus a heartbeat every 15 s.
    """
    logger.debug("SSE client connected")

    async def generate() -> AsyncGenerator[str, None]:
        try:
            while True:
                try:
                    event = await asyncio.wait_for(
                        _app_state.event_queue.get(), timeout=15.0
                    )
                    event_type = event.get("type", "message")
                    data = json.dumps(event)
                    yield f"event: {event_type}\ndata: {data}\n\n"
                except TimeoutError:
                    # Heartbeat to keep proxies from closing idle connections
                    yield "event: heartbeat\ndata: {}\n\n"
        except asyncio.CancelledError:
            logger.debug("SSE client disconnected")
            raise

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/run", status_code=202)
async def manual_run() -> JSONResponse:
    """
    Manually trigger a batch run in a background thread.

    Returns 202 immediately; the run proceeds asynchronously.
    """
    from batch import execute_run

    run_id = str(uuid.uuid4())
    logger.info("Manual /run triggered — run_id=%s", run_id)

    t = threading.Thread(
        target=execute_run,
        args=(_app_state,),
        daemon=True,
        name=f"manual-run-{run_id}",
    )
    t.start()

    return JSONResponse(
        {"run_id": run_id, "message": "Batch run queued"},
        status_code=202,
    )


@app.get("/healthz")
async def healthz() -> JSONResponse:
    """Health check endpoint."""
    return JSONResponse({"status": "ok"})


# ---------------------------------------------------------------------------
# Inline dashboard HTML
# ---------------------------------------------------------------------------

_DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>PMS Scanner Dashboard</title>
<style>
  body { font-family: monospace; background: #1a1a2e; color: #e0e0e0; padding: 20px; }
  h1   { color: #00d4ff; }
  #status-box { background: #16213e; border: 1px solid #0f3460; border-radius: 6px;
                padding: 16px; margin-top: 16px; }
  #filename  { font-size: 1.1em; color: #e94560; font-weight: bold; }
  #progress  { font-size: 2em; color: #00d4ff; margin: 8px 0; }
  #runstatus { color: #aaa; font-size: 0.9em; }
  #last-run  { margin-top: 20px; color: #888; font-size: 0.85em; }
  button { background: #0f3460; color: #e0e0e0; border: 1px solid #00d4ff;
           padding: 8px 16px; cursor: pointer; border-radius: 4px; margin-top: 12px; }
  button:hover { background: #00d4ff; color: #1a1a2e; }
</style>
</head>
<body>
<h1>PMS Scanner</h1>
<div id="status-box">
  <div id="runstatus">Connecting...</div>
  <div id="filename"></div>
  <div id="progress"></div>
</div>
<div id="last-run"></div>
<button onclick="triggerRun()">&#9654; Run Now</button>

<script>
const statusEl   = document.getElementById('runstatus');
const filenameEl = document.getElementById('filename');
const progressEl = document.getElementById('progress');
const lastRunEl  = document.getElementById('last-run');

function triggerRun() {
  fetch('/run', { method: 'POST' })
    .then(r => r.json())
    .then(d => { statusEl.textContent = 'Run queued: ' + d.run_id; });
}

// Load initial state
fetch('/status').then(r => r.json()).then(renderStatus);

function renderStatus(data) {
  if (data.last_run) {
    const lr = data.last_run;
    lastRunEl.textContent = 'Last run: ' + lr.run_id + ' (' + lr.status + ')' +
      ' — ' + (lr.files ? lr.files.length : 0) + ' file(s)';
  }
  if (!data.current_run) {
    statusEl.textContent = 'Idle — waiting for next scheduled run';
    filenameEl.textContent = '';
    progressEl.textContent = '';
  }
}

const es = new EventSource('/events');
es.addEventListener('run_started', e => {
  const d = JSON.parse(e.data);
  statusEl.textContent = 'Run started: ' + d.run_id;
  filenameEl.textContent = '';
  progressEl.textContent = '';
});
es.addEventListener('file_started', e => {
  const d = JSON.parse(e.data);
  filenameEl.textContent = d.filename;
  progressEl.textContent = '0 / ' + (d.total_pages || '?');
});
es.addEventListener('page_done', e => {
  const d = JSON.parse(e.data);
  filenameEl.textContent = d.filename;
  progressEl.textContent = d.page_num + ' / ' + d.total_pages;
});
es.addEventListener('file_done', e => {
  const d = JSON.parse(e.data);
  statusEl.textContent = 'File done: ' + d.filename + ' (' + d.status + ')';
});
es.addEventListener('run_done', e => {
  const d = JSON.parse(e.data);
  statusEl.textContent = 'Run complete (' + d.files + ' file(s))';
  filenameEl.textContent = '';
  progressEl.textContent = '';
  fetch('/status').then(r => r.json()).then(renderStatus);
});
es.addEventListener('heartbeat', () => {});
es.onerror = () => { statusEl.textContent = 'Connection lost — retrying...'; };
</script>
</body>
</html>
"""
