"""
File-system watcher that uploads new images to pms-backend.

Watches WATCH_DIR for new image files and POSTs them to:
  POST /api/scanned-images/upload

Request shape (multipart/form-data):
  files        list[UploadFile]  — one or more image files
  requisition_id  UUID (optional) — link images to an existing requisition

Response (BatchUploadResponse):
  batch_id  UUID
  images    list of {id, original_file_name, status, sort_order, batch_id}
  rejected  list of {file_name, reason}
"""

import time
import logging
import mimetypes
from pathlib import Path
from uuid import UUID

import requests
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

from config import settings

logger = logging.getLogger(__name__)

# Formats accepted by POST /api/scanned-images/upload
SUPPORTED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".tif", ".webp"}


def is_image(path: Path) -> bool:
    return path.suffix.lower() in SUPPORTED_EXTENSIONS


def upload_image(path: Path) -> bool:
    """
    Upload a single image to POST /api/scanned-images/upload.

    The backend field name is `files` (list[UploadFile]).
    Returns True if the file was accepted (not necessarily processed).
    """
    mime, _ = mimetypes.guess_type(str(path))
    mime = mime or "application/octet-stream"

    form_data: dict = {}
    if settings.requisition_id:
        form_data["requisition_id"] = str(settings.requisition_id)

    try:
        with path.open("rb") as f:
            response = requests.post(
                f"{settings.backend_base_url}/api/scanned-images/upload",
                headers={"Authorization": f"Bearer {settings.api_token}"},
                # `files` is a list on the backend — send as multi-value key
                files=[("files", (path.name, f, mime))],
                data=form_data,
                timeout=settings.upload_timeout_seconds,
            )
        response.raise_for_status()

        body = response.json()
        batch_id = body.get("batch_id", "?")
        accepted = [img["original_file_name"] for img in body.get("images", [])]
        rejected = body.get("rejected", [])

        if accepted:
            logger.info("Batch %s accepted: %s", batch_id, ", ".join(accepted))
        for rej in rejected:
            logger.warning(
                "Batch %s rejected %s: %s",
                batch_id,
                rej.get("file_name"),
                rej.get("reason"),
            )

        return bool(accepted)

    except requests.HTTPError as exc:
        logger.error(
            "HTTP %s uploading %s: %s",
            exc.response.status_code if exc.response is not None else "?",
            path.name,
            exc,
        )
    except requests.RequestException as exc:
        logger.error("Network error uploading %s: %s", path.name, exc)

    return False


class ImageEventHandler(FileSystemEventHandler):
    """Handles filesystem events for newly created/moved image files."""

    def _handle(self, event_path: str) -> None:
        path = Path(event_path)
        if path.is_file() and is_image(path):
            # Wait for the write to fully flush before reading.
            time.sleep(settings.file_settle_seconds)
            upload_image(path)

    def on_created(self, event):
        if not event.is_directory:
            self._handle(event.src_path)

    def on_moved(self, event):
        # Catches files atomically renamed/moved into the watch folder.
        if not event.is_directory:
            self._handle(event.dest_path)


def run() -> None:
    watch_dir = Path(settings.watch_dir)
    watch_dir.mkdir(parents=True, exist_ok=True)

    logger.info(
        "Watching %s (recursive=%s) -> %s/api/scanned-images/upload",
        watch_dir,
        settings.watch_recursive,
        settings.backend_base_url,
    )

    handler = ImageEventHandler()
    observer = Observer()
    observer.schedule(handler, str(watch_dir), recursive=settings.watch_recursive)
    observer.start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("Shutting down watcher.")
    finally:
        observer.stop()
        observer.join()
