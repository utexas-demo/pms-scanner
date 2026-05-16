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
from starlette.concurrency import run_in_threadpool

from .config import AppSettings
from .state import AppState, BatchRunState
from .state import app_state as _default_app_state

logger = logging.getLogger(__name__)

app = FastAPI(title="pms-scanner dashboard")

# ---------------------------------------------------------------------------
# State injection — tests can replace this
# ---------------------------------------------------------------------------

_app_state: AppState = _default_app_state

# 004 runtime injection — set by __main__/tests via configure().
_settings: AppSettings | None = None
_run_state: BatchRunState | None = None


def configure(settings: AppSettings, state: BatchRunState) -> None:
    """Wire the multi-env runtime into the dashboard (called by __main__)."""
    global _settings, _run_state
    _settings = settings
    _run_state = state

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


def _run_env_once(env_name: str) -> str:
    """Build a BatchRunner for ``env_name`` and execute one synchronous pass."""
    from .batch import BatchRunner

    assert _settings is not None and _run_state is not None
    env = next(e for e in _settings.environments if e.name == env_name)
    runner = BatchRunner(
        env,
        _settings.machine,
        _run_state,
        settle_seconds=_settings.file_settle_seconds,
        upload_timeout_seconds=_settings.upload_timeout_seconds,
        upload_max_retries=_settings.upload_max_retries,
        upload_retry_max_wait_seconds=_settings.upload_retry_max_wait_seconds,
        emit=_app_state.emit_event,
    )
    run_id = str(uuid.uuid4())
    logger.info(
        "Manual /run env=%s machine=%s run_id=%s",
        env_name,
        _settings.machine.name,
        run_id,
    )
    runner.run_once()
    return run_id


@app.post("/run", status_code=202)
async def manual_run(environment: str | None = None) -> JSONResponse:
    """Manually trigger a run.

    With ``?environment=<name>`` (004): synchronously run that single
    environment on this machine. Unknown env → 404. Without the param:
    legacy single-env behavior (replaced by T028 to fan out all envs).
    """
    if environment is not None:
        if _settings is None or _run_state is None:
            return JSONResponse(
                {"detail": "dashboard runtime not configured"},
                status_code=503,
            )
        names = [e.name for e in _settings.environments]
        if environment not in names:
            return JSONResponse(
                {
                    "detail": (
                        f"environment '{environment}' not configured on "
                        f"this machine"
                    )
                },
                status_code=404,
            )
        run_id = await run_in_threadpool(_run_env_once, environment)
        return JSONResponse(
            {
                "machine": _settings.machine.name,
                "triggered": [environment],
                "run_ids": {environment: run_id},
            },
            status_code=202,
        )

    # Legacy no-arg path (until T028).
    from .batch import execute_run

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
  h1, h2 { color: #00d4ff; }
  h2 { font-size: 1.1em; margin-top: 24px; border-bottom: 1px solid #0f3460; padding-bottom: 4px; }
  .run { background: #16213e; border: 1px solid #0f3460; border-radius: 6px;
         padding: 12px; margin: 10px 0; }
  .run.active { border-color: #00d4ff; }
  .run-header { display: flex; gap: 12px; align-items: center;
                color: #aaa; font-size: 0.85em; flex-wrap: wrap; }
  .run-id { color: #00d4ff; }
  .status-pill { padding: 2px 8px; border-radius: 10px; font-size: 0.8em; }
  .status-running   { background: #00d4ff; color: #1a1a2e; }
  .status-completed { background: #3ddc84; color: #1a1a2e; }
  .status-failed    { background: #e94560; color: #fff; }
  .file { margin: 6px 0 6px 10px; font-size: 0.9em; }
  .file-name { color: #e94560; font-weight: bold; }
  .progress-bar { background: #0f3460; height: 6px; border-radius: 3px;
                  margin-top: 4px; overflow: hidden; }
  .progress-fill { background: #00d4ff; height: 100%; transition: width 0.25s; }
  .file-status-completed .file-name { color: #3ddc84; }
  .file-status-failed    .file-name { color: #e94560; }
  .counters { color: #aaa; margin-left: 8px; font-size: 0.85em; }
  button { background: #0f3460; color: #e0e0e0; border: 1px solid #00d4ff;
           padding: 8px 16px; cursor: pointer; border-radius: 4px; margin-top: 12px; }
  button:hover { background: #00d4ff; color: #1a1a2e; }
  .empty { color: #666; font-style: italic; }
</style>
</head>
<body>
<h1>PMS Scanner</h1>
<button id="run-btn">&#9654; Run Now</button>

<h2>Active Runs <span id="active-count" class="counters"></span></h2>
<div id="active-runs"></div>

<h2>History <span id="history-count" class="counters"></span></h2>
<div id="history"></div>

<script>
const activeEl = document.getElementById('active-runs');
const historyEl = document.getElementById('history');
const activeCountEl = document.getElementById('active-count');
const historyCountEl = document.getElementById('history-count');

document.getElementById('run-btn').addEventListener('click', () => {
  fetch('/run', { method: 'POST' });
});

function fmtTime(iso) {
  if (!iso) return '';
  return new Date(iso).toLocaleTimeString();
}

function el(tag, cls, text) {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text !== undefined) n.textContent = text;
  return n;
}

function buildFile(f) {
  const wrap = el('div', 'file file-status-' + f.status);
  wrap.appendChild(el('span', 'file-name', f.filename));
  const pagesDone = (f.pages || []).length;
  const total = f.total_pages || 0;
  const failed = (f.pages || []).filter(p => !p.upload_success).length;
  const counters = total
    ? pagesDone + ' / ' + total + (failed ? ' (' + failed + ' failed)' : '') + ' — ' + f.status
    : 'scanning... — ' + f.status;
  wrap.appendChild(el('span', 'counters', counters));
  const bar = el('div', 'progress-bar');
  const fill = el('div', 'progress-fill');
  fill.style.width = (total ? (pagesDone / total * 100) : 0) + '%';
  bar.appendChild(fill);
  wrap.appendChild(bar);
  return wrap;
}

function buildRun(run, isActive) {
  const wrap = el('div', isActive ? 'run active' : 'run');
  const hdr = el('div', 'run-header');
  hdr.appendChild(el('span', 'run-id', run.run_id.slice(0, 8)));
  hdr.appendChild(el('span', 'status-pill status-' + run.status, run.status));
  const times = 'started ' + fmtTime(run.started_at) +
    (run.completed_at ? ' · done ' + fmtTime(run.completed_at) : '');
  hdr.appendChild(el('span', null, times));
  wrap.appendChild(hdr);
  const files = run.files || [];
  if (files.length === 0) {
    wrap.appendChild(el('div', 'file empty', 'no files yet'));
  } else {
    files.forEach(f => wrap.appendChild(buildFile(f)));
  }
  return wrap;
}

function replaceChildren(parent, nodes) {
  while (parent.firstChild) parent.removeChild(parent.firstChild);
  nodes.forEach(n => parent.appendChild(n));
}

function refresh() {
  fetch('/status').then(r => r.json()).then(data => {
    const active = data.active_runs || [];
    const history = data.history || [];
    activeCountEl.textContent = active.length ? '(' + active.length + ')' : '';
    historyCountEl.textContent = history.length ? '(' + history.length + ')' : '';
    if (active.length === 0) {
      replaceChildren(activeEl, [el('div', 'empty', 'Idle — waiting for next scheduled run')]);
    } else {
      replaceChildren(activeEl, active.map(r => buildRun(r, true)));
    }
    replaceChildren(historyEl, history.map(r => buildRun(r, false)));
  });
}

refresh();

const es = new EventSource('/events');
['run_started', 'file_started', 'page_done', 'file_done', 'run_done'].forEach(t => {
  es.addEventListener(t, () => refresh());
});
es.addEventListener('heartbeat', () => {});
</script>
</body>
</html>
"""
