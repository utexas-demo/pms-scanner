"""
Upload a single rendered PDF page (PIL Image) to POST /api/scanned-images/upload.

Retry strategy
--------------
Transient server errors (HTTP 5xx and network failures) are retried up to
settings.upload_max_retries total attempts, with exponential back-off capped
at settings.upload_retry_max_wait_seconds.  Client errors (HTTP 4xx) are NOT
retried — they indicate a permanent failure (bad auth, bad payload, etc.) and
are returned immediately as False.
"""

import io
import logging
import time
from pathlib import Path

import requests
from config import settings
from PIL import Image

logger = logging.getLogger(__name__)


def upload_page(
    path: Path,
    page_num: int,
    total_pages: int,
    image: Image.Image,
) -> bool:
    """
    Upload one rendered PDF page to the backend.

    Parameters
    ----------
    path:        Source PDF path — used to derive the per-page filename.
    page_num:    1-indexed page number within the PDF.
    total_pages: Total page count in the PDF (for log messages only).
    image:       Rendered page as a PIL Image (will be encoded as JPEG).

    Returns
    -------
    True if the backend returned HTTP 2xx and accepted the image.
    False on any permanent or exhausted-retry failure.
    """
    filename = f"{path.stem}_p{page_num:03d}.jpg"
    url = f"{settings.backend_base_url}/api/scanned-images/upload"
    headers = {"Authorization": f"Bearer {settings.api_token}"}

    form_data: dict[str, str] = {}
    if settings.requisition_id:
        form_data["requisition_id"] = str(settings.requisition_id)

    max_attempts = settings.upload_max_retries
    max_wait = settings.upload_retry_max_wait_seconds

    for attempt in range(max_attempts):
        image_bytes = _encode_jpeg(image)
        try:
            response = requests.post(
                url,
                headers=headers,
                files=[("files", (filename, image_bytes, "image/jpeg"))],
                data=form_data,
                timeout=settings.upload_timeout_seconds,
            )
            response.raise_for_status()

            body = response.json()
            batch_id = body.get("batch_id", "?")
            accepted = [img["original_file_name"] for img in body.get("images", [])]
            rejected = body.get("rejected", [])

            if accepted:
                logger.info(
                    "Uploaded %s (page %d/%d) → batch %s",
                    filename,
                    page_num,
                    total_pages,
                    batch_id,
                )
            for rej in rejected:
                logger.warning(
                    "Backend rejected %s in batch %s: %s",
                    rej.get("file_name"),
                    batch_id,
                    rej.get("reason"),
                )

            return bool(accepted)

        except requests.HTTPError as exc:
            status = exc.response.status_code if exc.response is not None else 0
            if status < 500:
                # 4xx — permanent client error, no retry
                logger.error(
                    "HTTP %d uploading %s (page %d/%d): %s",
                    status,
                    filename,
                    page_num,
                    total_pages,
                    exc,
                )
                return False
            # 5xx — transient server error, retry
            logger.warning(
                "HTTP %d uploading %s (page %d/%d), attempt %d/%d",
                status,
                filename,
                page_num,
                total_pages,
                attempt + 1,
                max_attempts,
            )

        except requests.RequestException as exc:
            logger.warning(
                "Network error uploading %s (page %d/%d), attempt %d/%d: %s",
                filename,
                page_num,
                total_pages,
                attempt + 1,
                max_attempts,
                exc,
            )

        if attempt < max_attempts - 1:
            wait_seconds = min(2**attempt, max_wait)
            time.sleep(wait_seconds)

    logger.error(
        "Exhausted %d upload attempts for %s (page %d/%d)",
        max_attempts,
        filename,
        page_num,
        total_pages,
    )
    return False


def _encode_jpeg(image: Image.Image) -> bytes:
    """Encode a PIL Image to JPEG bytes."""
    buf = io.BytesIO()
    image.save(buf, format="JPEG")
    return buf.getvalue()
