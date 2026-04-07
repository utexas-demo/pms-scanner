"""
File-system watcher that uploads new images to pms-backend.
Watches WATCH_DIR for new image files and POSTs them to the backend API.
"""

import os
import time
import logging
import mimetypes
from pathlib import Path

import requests
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

from config import settings

logger = logging.getLogger(__name__)

SUPPORTED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tiff", ".webp"}


def is_image(path: Path) -> bool:
    return path.suffix.lower() in SUPPORTED_EXTENSIONS


def upload_image(path: Path) -> bool:
    """Upload a single image file to the pms-backend. Returns True on success."""
    mime, _ = mimetypes.guess_type(str(path))
    mime = mime or "application/octet-stream"

    try:
        with path.open("rb") as f:
            response = requests.post(
                settings.backend_upload_url,
                headers={"Authorization": f"Bearer {settings.api_token}"},
                files={"file": (path.name, f, mime)},
                data={"folder": str(path.parent.relative_to(settings.watch_dir))},
                timeout=settings.upload_timeout_seconds,
            )
        response.raise_for_status()
        logger.info("Uploaded %s -> HTTP %s", path.name, response.status_code)
        return True
    except requests.HTTPError as exc:
        logger.error("HTTP error uploading %s: %s", path.name, exc)
    except requests.RequestException as exc:
        logger.error("Network error uploading %s: %s", path.name, exc)
    return False


class ImageEventHandler(FileSystemEventHandler):
    """Handles filesystem events for newly created/moved image files."""

    def _handle(self, event_path: str) -> None:
        path = Path(event_path)
        if path.is_file() and is_image(path):
            # Brief pause to ensure the file is fully written before reading.
            time.sleep(settings.file_settle_seconds)
            upload_image(path)

    def on_created(self, event):
        if not event.is_directory:
            self._handle(event.src_path)

    def on_moved(self, event):
        # A file moved/renamed into the watch folder
        if not event.is_directory:
            self._handle(event.dest_path)


def run() -> None:
    watch_dir = Path(settings.watch_dir)
    watch_dir.mkdir(parents=True, exist_ok=True)

    logger.info("Watching %s for new images...", watch_dir)

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
