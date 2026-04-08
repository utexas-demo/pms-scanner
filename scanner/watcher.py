"""
File-system watcher that uploads new images to pms-backend.
Watches WATCH_DIR for new image files, queues them, and POSTs each to the backend API.
"""

from __future__ import annotations

import logging
import mimetypes
import queue
import shutil
import signal
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final, NamedTuple

import requests
import tenacity
from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer
from watchdog.observers.api import BaseObserver

from scanner.config import settings
from scanner.store import FileRecord, Status, status_store

logger = logging.getLogger(__name__)

SUPPORTED_EXTENSIONS: Final[frozenset[str]] = frozenset(
    {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tiff", ".webp"}
)

# Duplicate-event suppression: ignore repeated events for the same path within this window.
_DEDUP_WINDOW_SECONDS: Final[float] = 2.0

# Retry wait strategy.  Patch `scanner.watcher._RETRY_WAIT = None` in tests to skip delays.
_RETRY_WAIT: Any = tenacity.wait_exponential(multiplier=1, min=1, max=10) + tenacity.wait_random(
    0, 1
)


class QueueItem(NamedTuple):
    """Pairs a file path with its StatusStore record ID for tracking."""

    path: Path
    record_id: str


@dataclass
class UploadResult:
    """Outcome of a single upload pipeline run (including all retry attempts)."""

    success: bool
    file_path: Path
    http_status: int | None = None
    error_message: str | None = None
    attempts: int = 1
    completed_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    destination_path: Path | None = None


class _NonRetriableError(Exception):
    """Raised for HTTP 4xx responses that must not be retried."""

    def __init__(self, response: requests.Response) -> None:
        self.response = response
        super().__init__(f"HTTP {response.status_code}")


def is_image(path: Path) -> bool:
    """Return True if *path* has a supported image file extension."""
    return path.suffix.lower() in SUPPORTED_EXTENSIONS


def upload_image(path: Path) -> UploadResult:
    """Upload *path* to the backend.

    Retries on network errors and HTTP 5xx (max 3 attempts, exponential back-off).
    Does NOT retry on HTTP 4xx.  Never raises — always returns an UploadResult.
    """
    from scanner import watcher as _mod  # late import so tests can patch _RETRY_WAIT

    wait: Any = _mod._RETRY_WAIT if _mod._RETRY_WAIT is not None else tenacity.wait_none()

    watch_dir = Path(settings.watch_dir)
    processed_dir = watch_dir / "processed"
    mime, _ = mimetypes.guess_type(str(path))
    mime = mime or "application/octet-stream"
    try:
        folder = str(path.parent.relative_to(watch_dir))
    except ValueError:
        folder = ""

    session = requests.Session()
    attempts = 0
    response: requests.Response | None = None

    def _before_sleep(retry_state: tenacity.RetryCallState) -> None:
        exc = retry_state.outcome.exception() if retry_state.outcome else "unknown"
        logger.warning(
            "Retrying upload of %s (attempt %d of 3): %s",
            path.name,
            retry_state.attempt_number,
            exc,
        )

    try:
        for attempt in tenacity.Retrying(
            stop=tenacity.stop_after_attempt(3),
            wait=wait,
            retry=tenacity.retry_if_exception_type(requests.RequestException),
            before_sleep=_before_sleep,
            reraise=True,
        ):
            with attempt:
                attempts += 1
                with path.open("rb") as fh:
                    resp = session.post(
                        settings.backend_upload_url,
                        headers={"Authorization": f"Bearer {settings.api_token}"},
                        files={"file": (path.name, fh, mime)},
                        data={"folder": folder},
                        timeout=settings.upload_timeout_seconds,
                    )
                if resp.status_code >= 500:
                    # Retriable — tenacity will retry this
                    raise requests.HTTPError(f"HTTP {resp.status_code}", response=resp)
                if not resp.ok:
                    # Non-retriable (4xx) — propagates immediately out of Retrying loop
                    raise _NonRetriableError(resp)
                response = resp

        assert response is not None
        logger.info("Uploaded %s → HTTP %s", path.name, response.status_code)
        return UploadResult(
            success=True,
            file_path=path,
            http_status=response.status_code,
            attempts=attempts,
            destination_path=processed_dir / path.name,
        )

    except _NonRetriableError as exc:
        msg = f"HTTP {exc.response.status_code} — will not retry"
        logger.error("Upload rejected for %s: %s", path.name, msg)
        return UploadResult(
            success=False,
            file_path=path,
            http_status=exc.response.status_code,
            error_message=msg,
            attempts=attempts,
        )

    except requests.RequestException as exc:
        msg = str(exc)
        logger.error(
            "Upload failed for %s after %d attempt(s): %s",
            path.name,
            attempts,
            msg,
        )
        return UploadResult(
            success=False,
            file_path=path,
            error_message=msg,
            attempts=attempts,
        )


def process_file(
    path: Path,
    watch_dir: Path,
    processed_dir: Path,
    record_id: str | None = None,
) -> None:
    """Settle, upload, then move to processed/ on success or leave in place on failure."""
    time.sleep(settings.file_settle_seconds)

    if not path.exists():
        logger.warning("File disappeared before upload: %s", path.name)
        return

    if record_id is not None:
        status_store.update(record_id, status=Status.UPLOADING)

    result = upload_image(path)

    if result.success and result.destination_path is not None:
        processed_dir.mkdir(parents=True, exist_ok=True)
        shutil.move(str(path), str(result.destination_path))
        logger.info("Moved %s → processed/", path.name)
        if record_id is not None:
            status_store.update(
                record_id,
                status=Status.SUCCESS,
                attempts=result.attempts,
            )
    else:
        logger.error(
            "Upload failed for %s after %d attempt(s): %s"
            " — left in watch root for retry on restart",
            path.name,
            result.attempts,
            result.error_message,
        )
        if record_id is not None:
            status_store.update(
                record_id,
                status=Status.FAILED,
                error_message=result.error_message or "Unknown error",
                attempts=result.attempts,
            )


class ImageEventHandler(FileSystemEventHandler):
    """Watchdog handler: enqueues detected image files, suppressing duplicates."""

    def __init__(self, upload_queue: queue.Queue[QueueItem]) -> None:
        super().__init__()
        self._queue = upload_queue
        self._seen: dict[str, float] = {}
        self._lock = threading.Lock()

    def _handle(self, event_path: str) -> None:
        path = Path(event_path).resolve()

        # Exclude the processed/ subfolder to prevent re-uploading moved files.
        watch_dir = Path(settings.watch_dir).resolve()
        processed_dir = watch_dir / "processed"
        try:
            path.relative_to(processed_dir)
            return  # inside processed/ — skip
        except ValueError:
            pass

        if not path.is_file() or not is_image(path):
            return

        now = time.monotonic()
        key = str(path)
        with self._lock:
            if now - self._seen.get(key, 0.0) < _DEDUP_WINDOW_SECONDS:
                return  # duplicate event within dedup window
            self._seen[key] = now

        record_id = str(uuid.uuid4())
        status_store.add(
            FileRecord(
                id=record_id,
                filename=path.name,
                status=Status.PENDING,
                detected_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
                error_message=None,
                attempts=0,
            )
        )
        logger.debug("Detected %s (record %s)", path.name, record_id)
        self._queue.put(QueueItem(path=path, record_id=record_id))

    def on_created(self, event: FileSystemEvent) -> None:
        if not event.is_directory:
            src = event.src_path
            self._handle(src if isinstance(src, str) else src.decode())

    def on_moved(self, event: FileSystemEvent) -> None:
        if not event.is_directory:
            dest = getattr(event, "dest_path", None)
            if dest:
                self._handle(str(dest))


def build_observer(
    watch_dir: Path,
    processed_dir: Path,
) -> tuple[BaseObserver, threading.Thread]:
    """Create a configured Observer + worker thread pair.

    The worker exits automatically once the observer stops and the queue is drained.
    Shutdown sequence: observer.stop() → observer.join() → worker.join().
    """
    upload_queue: queue.Queue[QueueItem] = queue.Queue(maxsize=100)
    handler = ImageEventHandler(upload_queue)

    observer = Observer()
    observer.schedule(handler, str(watch_dir), recursive=settings.watch_recursive)

    def _worker() -> None:
        while True:
            try:
                item = upload_queue.get(timeout=0.5)
                process_file(item.path, watch_dir, processed_dir, record_id=item.record_id)
                upload_queue.task_done()
            except queue.Empty:
                # Exit only when observer is dead and there is nothing left to process.
                if not observer.is_alive() and upload_queue.empty():
                    break

    worker_thread = threading.Thread(target=_worker, name="upload-worker", daemon=True)
    return observer, worker_thread


def run() -> None:  # pragma: no cover
    """Start the file watcher service. Blocks until SIGTERM or KeyboardInterrupt."""
    import uvicorn

    from scanner.api import app

    watch_dir = Path(settings.watch_dir).resolve()
    processed_dir = watch_dir / "processed"
    watch_dir.mkdir(parents=True, exist_ok=True)
    processed_dir.mkdir(parents=True, exist_ok=True)

    # Start dashboard API server in a background thread.
    uvi_config = uvicorn.Config(
        app, host="0.0.0.0", port=settings.dashboard_port, log_level="warning"
    )
    server = uvicorn.Server(uvi_config)
    api_thread = threading.Thread(target=server.run, name="api-server", daemon=True)
    api_thread.start()
    logger.info("Dashboard server started on port %d", settings.dashboard_port)

    observer, worker = build_observer(watch_dir, processed_dir)

    shutdown = threading.Event()

    def _signal_handler(signum: int, frame: object) -> None:
        logger.info("Signal %d received — shutting down gracefully", signum)
        shutdown.set()

    signal.signal(signal.SIGTERM, _signal_handler)

    logger.info(
        "pms-scanner starting | watch_dir=%s | backend_url=%s | api_token=%s***",
        watch_dir,
        settings.backend_upload_url,
        settings.api_token[:4],
    )

    observer.start()
    worker.start()

    try:
        while not shutdown.is_set():
            time.sleep(0.5)
    except KeyboardInterrupt:
        logger.info("KeyboardInterrupt received — shutting down")
    finally:
        logger.info("Stopping observer and draining upload queue...")
        server.should_exit = True
        observer.stop()
        observer.join()
        worker.join(timeout=30)
        logger.info("pms-scanner stopped.")
