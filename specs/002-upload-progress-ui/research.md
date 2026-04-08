# Research: Upload Progress Dashboard

**Branch**: `002-upload-progress-ui` | **Date**: 2026-04-08

---

## R-001: ASGI Server — Running uvicorn alongside watchdog

**Decision**: `uvicorn.Server` (config object) started via `threading.Thread`, with a custom subclass that sets a `started` event once the server is accepting connections. Shutdown via `server.should_exit = True`.

**Rationale**: Gives explicit lifecycle control (start, ready-detect, graceful shutdown) without blocking the main watchdog loop. A daemon thread means the process exits cleanly even if the server hasn't shut down gracefully. `uvicorn.run()` in a plain thread is simpler but harder to detect readiness and harder to stop cleanly.

**Alternatives considered**:
- `uvicorn.run()` in a plain thread: simpler to set up but no readiness signal; shutdown requires `os.kill` or equivalent.
- asyncio.create_task: requires the whole main loop to be async, incompatible with blocking watchdog.

---

## R-002: SSE Library — sse-starlette

**Decision**: `sse-starlette>=2.1.0` via `EventSourceResponse`.

**Rationale**: Production-ready, W3C-compliant, handles client disconnects gracefully, explicit Python 3.12 support, includes heartbeat/reconnect logic. Preferred over manual `StreamingResponse` or Starlette's bare `EventSourceResponse` wrapper.

**Alternatives considered**:
- Plain Starlette `StreamingResponse` with manual `data: ...\n\n` formatting: error-prone, no disconnect handling.
- `anyio.create_memory_object_stream`: lower-level; requires manual SSE formatting on top.

---

## R-003: Thread-to-asyncio Bridge

**Decision**: `asyncio.run_coroutine_threadsafe(coro, loop)` to push events from the scanner worker thread into the uvicorn event loop.

**Rationale**: Returns a `concurrent.futures.Future`; calling `.result(timeout=1)` from the worker thread verifies the event was queued. This is the idiomatic cross-thread→asyncio bridge and avoids race conditions. The StatusStore keeps a reference to the event loop captured at server startup.

**Alternatives considered**:
- `loop.call_soon_threadsafe(callback)`: only accepts plain callables, not coroutines; requires an extra wrapping step.
- Polling with `threading.Event`: unnecessary overhead; coroutine submission is cleaner.

---

## R-004: Shared State Architecture

**Decision**: Module-level singleton `status_store` in `scanner/store.py`. `StatusStore` holds a `threading.Lock`-protected `dict[str, FileRecord]` and a `list[asyncio.Queue[str]]` of per-client SSE queues. The uvicorn event loop reference is stored at server startup.

**Rationale**: Singleton pattern mirrors the existing `settings` singleton. Thread-safe reads/writes with a `Lock`; asyncio queues used only within the event loop (push from worker via `run_coroutine_threadsafe`). Simple, minimal, no external dependencies.

**Alternatives considered**:
- Redis pub/sub: overkill for in-process communication; adds a service dependency.
- `multiprocessing.Queue`: only needed if processes are separate; this is single-process.

---

## R-005: HTML Serving Strategy

**Decision**: Embed the dashboard as a string constant in `scanner/api.py`. Serve via `@app.get("/")` returning `HTMLResponse(DASHBOARD_HTML)`.

**Rationale**: No external file dependency, no build step, trivially versionable in source control, fastest possible load (no file I/O). Appropriate for a single dashboard page.

**Alternatives considered**:
- Separate `.html` file with `FileResponse`: adds file dependency; no advantage for one page.
- Jinja2 templates: over-engineered; no templating needed.
- StaticFiles mount: requires directory setup; adds unnecessary complexity.

---

## R-006: New Dependencies

**Decision**:
```
fastapi>=0.100.0
uvicorn[standard]>=0.24.0
sse-starlette>=2.1.0
```
Added to `requirements.txt`. `uvicorn[standard]` includes optional speedups (uvloop, httptools) on Linux/Docker; falls back gracefully on Windows where uvloop is unavailable.

`anyio>=4.0.0` is pulled in transitively by Starlette; no explicit declaration needed.

**Rationale**: All three are Python 3.12-compatible and actively maintained as of 2026. No known incompatibilities with existing dependencies (watchdog, requests, tenacity, pydantic-settings).

**Alternatives considered**: None — these are the standard FastAPI stack.
