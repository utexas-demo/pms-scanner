# Research: Folder Monitor and File Upload

**Branch**: `001-folder-monitor-upload` | **Phase**: 0 | **Date**: 2026-04-08

## R-001: watchdog Event Strategy on Windows

**Decision**: Keep `on_created` + 0.5-second settle delay. Do NOT rely on `on_closed`.

**Rationale**: watchdog's `FileClosedEvent` (`on_closed`) has severe limitations on Windows because `ReadDirectoryChangesW` (the underlying Win32 API) does not reliably report file-close events — it misses events and can report them in incorrect forms. Linux's `inotify` `IN_CLOSE_WRITE` has no equivalent on Windows. The `on_created` + settle-sleep pattern is the community-proven approach for Windows file detection.

**Alternatives considered**:
- `on_closed` on Windows — unreliable; rejected
- `on_modified` + try-read loop — more complex and not meaningfully more reliable than the sleep approach for the target use case

**Key caveat**: The 0.5-second settle is hardcoded in the spec (FR-002). It is configurable via `FILE_SETTLE_SECONDS`. For large files or slow storage (USB, network shares), operators should increase this value.

---

## R-002: HTTP Retry with Exponential Back-off

**Decision**: Use `tenacity` library — `@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=10) + wait_random(0, 1))`.

**Rationale**: `tenacity` is the de-facto standard Python retry library. It provides clean decorator-based API, exponential back-off, random jitter (essential for preventing thundering-herd retries), and structured logging hooks. Manual `time.sleep` loops are error-prone and hard to maintain. The `requests` built-in `urllib3.Retry` is adequate for connection-level retries but is less flexible for application-level logic (e.g., retry on specific HTTP status codes with back-off).

**Alternatives considered**:
- `urllib3.Retry` with `HTTPAdapter` — covers connection errors only; does not retry on 5xx responses with back-off; rejected
- Manual retry loop — rejected (error-prone, inconsistent jitter)

**Configuration**: 3 attempts, exponential back-off (1s → 2s → 4s max 10s), ±1s random jitter. Retries on network errors and 5xx responses. 4xx errors are NOT retried (auth failure, bad request — these require operator intervention).

---

## R-003: SIGTERM Handling in Docker (Linux Container)

**Decision**: Register `signal.SIGTERM` handler that sets a shutdown flag and calls `observer.stop()`. The Docker image uses `python:3.12-slim` (Linux), so POSIX signals work correctly.

**Rationale**: Docker sends SIGTERM to PID 1 before SIGKILL on `docker stop`. If the process doesn't handle SIGTERM, it gets forcibly killed after the stop timeout (default 10s), potentially dropping in-flight uploads. The `CMD ["python", "-m", "scanner"]` in Dockerfile uses exec-form (not shell-form), so the Python process IS PID 1 and receives signals directly.

**Alternatives considered**:
- Windows-native shutdown flag file — not needed; service runs in a Linux container (Docker Desktop on Windows uses WSL2/HyperV Linux VM)
- `atexit` hook — only runs on normal Python exit, not on SIGTERM

**Implementation pattern**:
```python
import signal, threading

_shutdown_event = threading.Event()

def _sigterm_handler(signum, frame):
    logger.info("SIGTERM received — initiating graceful shutdown")
    _shutdown_event.set()

signal.signal(signal.SIGTERM, _sigterm_handler)
```

---

## R-004: Concurrent File Queue Pattern

**Decision**: Use `queue.Queue` + dedicated worker thread. Decouple event detection from upload processing.

**Rationale**: The current code runs the 0.5s sleep and HTTP upload *inside* the watchdog event handler. This blocks watchdog's internal event thread during uploads, causing queued events to back up and potentially be dropped — especially on Windows where the ReadDirectoryChangesW buffer is finite. A `queue.Queue` + worker pattern keeps the event handler non-blocking (just enqueues the path) and lets uploads proceed at their own pace.

**Alternatives considered**:
- `ThreadPoolExecutor` per-file — simpler but offers no backpressure; risks OOM on upload stalls; rejected
- Stay with blocking handler — rejected; violates FR-007 (no-drop guarantee)

**Deduplication**: Windows fires duplicate `on_created` events for the same file in rapid succession. Mitigation: a time-windowed seen-set keyed on the resolved absolute path, with entries expiring after 2 seconds.

---

## R-005: requests.Session Thread Safety

**Decision**: Create one `requests.Session` per worker thread; do NOT share a single session across threads.

**Rationale**: `requests.Session` has mutable state (headers, cookies, adapters). Concurrent mutation from multiple threads causes race conditions. Since we use a single worker thread (queue consumer), one session per worker is the correct pattern and maintains connection-pool efficiency without risk.

---

## R-006: Startup Configuration Logging (Constitution IV)

**Decision**: Log all configuration values at startup at INFO level. Redact `api_token` — log only the first 4 characters followed by `***`.

**Rationale**: Constitution Principle IV requires startup config to be logged (with secrets redacted). This gives operators visibility into the running configuration without exposing credentials in log files.

**Pattern**:
```python
logger.info("Starting pms-scanner with config: watch_dir=%s, backend_url=%s, api_token=%s***",
            settings.watch_dir, settings.backend_upload_url, settings.api_token[:4])
```
