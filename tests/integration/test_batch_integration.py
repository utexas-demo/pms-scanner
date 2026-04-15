"""Integration test for a full batch run against a real PDF — T014."""
import os
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from PIL import Image
from pytest_httpserver import HTTPServer


def _make_minimal_pdf() -> bytes:
    """Return the bytes of a valid 1-page PDF."""
    return (
        b"%PDF-1.4\n"
        b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
        b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
        b"3 0 obj<</Type/Page/MediaBox[0 0 612 792]/Parent 2 0 R>>endobj\n"
        b"xref\n0 4\n"
        b"0000000000 65535 f\n"
        b"0000000009 00000 n\n"
        b"0000000058 00000 n\n"
        b"0000000115 00000 n\n"
        b"trailer<</Size 4/Root 1 0 R>>\nstartxref\n190\n%%EOF"
    )


def test_execute_run_full_pipeline(tmp_path: Path, httpserver: HTTPServer):
    """
    Full integration: 1-page PDF → process → upload to mock server → processed/.
    """
    # Set up mock HTTP server to accept the upload
    httpserver.expect_request(
        "/api/scanned-images/upload",
        method="POST",
    ).respond_with_json(
        {
            "batch_id": "test-batch-001",
            "images": [{"original_file_name": "scan_001_p001.jpg"}],
            "rejected": [],
        }
    )

    watch_dir = tmp_path / "ARIAscans"
    watch_dir.mkdir()
    (watch_dir / "in-progress").mkdir()
    (watch_dir / "processed").mkdir()

    pdf_file = watch_dir / "scan_001.pdf"
    pdf_file.write_bytes(_make_minimal_pdf())

    dummy_image = Image.new("RGB", (100, 100), color=(200, 200, 200))

    with (
        patch_env(httpserver.url_for(""), watch_dir),
        patch("batch.process_pdf", return_value=[(1, dummy_image, False, 0)]),
        patch("batch.upload_page", return_value=True) as mock_upload,
    ):
        from batch import execute_run
        from state import AppState

        state = AppState()
        execute_run(state)

    # File must be in processed/
    assert (watch_dir / "processed" / "scan_001.pdf").exists()
    assert not (watch_dir / "scan_001.pdf").exists()
    mock_upload.assert_called_once()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@contextmanager
def patch_env(backend_url: str, watch_dir: Path):
    env = {
        "BACKEND_BASE_URL": backend_url,
        "API_TOKEN": "test-token",
        "WATCH_DIR": str(watch_dir),
        "FILE_SETTLE_SECONDS": "0",
    }
    with patch.dict(os.environ, env):
        yield
