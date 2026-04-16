"""Unit tests for scanner/batch.py — T013."""
import os
from pathlib import Path
from unittest.mock import patch

import pytest
from PIL import Image


def _make_app_state():
    with patch.dict(os.environ, {"BACKEND_BASE_URL": "http://x", "API_TOKEN": "t"}):
        from state import AppState
        return AppState()


@pytest.fixture()
def watch_dir(tmp_path: Path) -> Path:
    d = tmp_path / "ARIAscans"
    d.mkdir()
    (d / "in-progress").mkdir()
    (d / "processed").mkdir()
    return d


@pytest.fixture()
def dummy_pdf(watch_dir: Path) -> Path:
    """Copy a minimal valid PDF into the watch directory."""
    p = watch_dir / "scan_001.pdf"
    # Minimal 1-page PDF that PyMuPDF can parse
    p.write_bytes(
        b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
        b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
        b"3 0 obj<</Type/Page/MediaBox[0 0 612 792]/Parent 2 0 R>>endobj\n"
        b"xref\n0 4\n0000000000 65535 f\n"
        b"0000000009 00000 n\n0000000058 00000 n\n0000000115 00000 n\n"
        b"trailer<</Size 4/Root 1 0 R>>\nstartxref\n190\n%%EOF"
    )
    return p


def test_crash_recovery_moves_inprogress_back_to_watch(watch_dir: Path):
    """On startup, files in in-progress/ are returned to the watch folder."""
    stranded = watch_dir / "in-progress" / "stranded.pdf"
    stranded.write_bytes(b"dummy")

    with patch.dict(
        os.environ,
        {"BACKEND_BASE_URL": "http://x", "API_TOKEN": "t", "WATCH_DIR": str(watch_dir)},
    ):
        state = _make_app_state()
        from batch import startup
        startup(state)

    assert not stranded.exists()
    assert (watch_dir / "stranded.pdf").exists()


def test_settle_filter_skips_recently_modified_files(watch_dir: Path):
    """Files modified within file_settle_seconds are skipped."""
    pdf = watch_dir / "fresh.pdf"
    pdf.write_bytes(b"dummy")
    # file was just written — should be within settle window

    claimed_files = []

    def fake_rename(dest):
        claimed_files.append(dest)

    with patch.dict(
        os.environ,
        {
            "BACKEND_BASE_URL": "http://x",
            "API_TOKEN": "t",
            "WATCH_DIR": str(watch_dir),
            "FILE_SETTLE_SECONDS": "3600",  # huge settle window — nothing passes
        },
    ):
        state = _make_app_state()
        with patch("batch.process_pdf", return_value=[]):
            from batch import execute_run
            execute_run(state)

    # File must still be in watch_dir (not claimed)
    assert pdf.exists()


def test_atomic_claim_renames_to_inprogress(watch_dir: Path, dummy_pdf: Path):
    """A PDF that passes the settle filter is renamed into in-progress/."""
    inprogress_path = watch_dir / "in-progress" / dummy_pdf.name
    dummy_image = Image.new("RGB", (10, 10))

    with patch.dict(
        os.environ,
        {
            "BACKEND_BASE_URL": "http://x",
            "API_TOKEN": "t",
            "WATCH_DIR": str(watch_dir),
            "FILE_SETTLE_SECONDS": "0",
        },
    ):
        state = _make_app_state()
        with patch("batch.process_pdf", return_value=[(1, dummy_image, False, 0)]):
            with patch("batch.upload_page", return_value=True):
                from batch import execute_run
                execute_run(state)

    # After success the file should be in processed/, not in-progress/
    assert not inprogress_path.exists()
    assert (watch_dir / "processed" / dummy_pdf.name).exists()


def test_failed_file_returned_to_watch_dir(watch_dir: Path, dummy_pdf: Path):
    """If upload fails, the PDF is returned from in-progress/ to watch_dir."""
    dummy_image = Image.new("RGB", (10, 10))

    with patch.dict(
        os.environ,
        {
            "BACKEND_BASE_URL": "http://x",
            "API_TOKEN": "t",
            "WATCH_DIR": str(watch_dir),
            "FILE_SETTLE_SECONDS": "0",
        },
    ):
        state = _make_app_state()
        with patch("batch.process_pdf", return_value=[(1, dummy_image, False, 0)]):
            with patch("batch.upload_page", return_value=False):
                from batch import execute_run
                execute_run(state)

    # File should be back in watch_dir
    assert (watch_dir / dummy_pdf.name).exists()
    assert not (watch_dir / "in-progress" / dummy_pdf.name).exists()


def test_successful_file_moved_to_processed(watch_dir: Path, dummy_pdf: Path):
    """Successful file ends up in processed/ and not in watch_dir."""
    dummy_image = Image.new("RGB", (10, 10))

    with patch.dict(
        os.environ,
        {
            "BACKEND_BASE_URL": "http://x",
            "API_TOKEN": "t",
            "WATCH_DIR": str(watch_dir),
            "FILE_SETTLE_SECONDS": "0",
        },
    ):
        state = _make_app_state()
        with patch("batch.process_pdf", return_value=[(1, dummy_image, False, 0)]):
            with patch("batch.upload_page", return_value=True):
                from batch import execute_run
                execute_run(state)

    assert (watch_dir / "processed" / dummy_pdf.name).exists()
    assert not (watch_dir / dummy_pdf.name).exists()


def test_missing_watch_dir_logs_error_and_returns(tmp_path: Path, caplog):
    """If watch_dir does not exist, log ERROR and return without crashing."""
    nonexistent = tmp_path / "does-not-exist"

    with patch.dict(
        os.environ,
        {"BACKEND_BASE_URL": "http://x", "API_TOKEN": "t", "WATCH_DIR": str(nonexistent)},
    ):
        import logging
        state = _make_app_state()
        with caplog.at_level(logging.ERROR, logger="batch"):
            from batch import execute_run
            execute_run(state)

    assert any(
        "does not exist" in r.message.lower() or "watch" in r.message.lower()
        for r in caplog.records
    )
