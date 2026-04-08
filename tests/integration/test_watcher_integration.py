"""Integration tests for the watchdog observer + queue worker pipeline.

TDD: must FAIL before watcher.py is refactored.
These tests start the real observer against a temp directory and use
responses/mock to simulate the HTTP backend.
"""

import time
from collections.abc import Callable
from pathlib import Path
from unittest.mock import patch

import responses as rsps_lib

ENDPOINT = "https://api.test/upload"
TOKEN = "integration-token"
_SETTLE = 0.05  # Very short settle for fast tests
_TIMEOUT = 8.0  # Generous but bounded wait for async worker


def _mock_settings(mock_cfg: object, watch_dir: Path) -> None:
    mock_cfg.backend_upload_url = ENDPOINT  # type: ignore[attr-defined]
    mock_cfg.api_token = TOKEN  # type: ignore[attr-defined]
    mock_cfg.upload_timeout_seconds = 5  # type: ignore[attr-defined]
    mock_cfg.watch_dir = str(watch_dir)  # type: ignore[attr-defined]
    mock_cfg.file_settle_seconds = _SETTLE  # type: ignore[attr-defined]
    mock_cfg.watch_recursive = True  # type: ignore[attr-defined]
    mock_cfg.log_level = "DEBUG"  # type: ignore[attr-defined]


def _wait_for(condition: Callable[[], bool], timeout: float = _TIMEOUT) -> bool:
    """Poll condition() until True or timeout (seconds). Returns whether condition was met."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.1)
    return False


# ---------------------------------------------------------------------------
# T010: end-to-end happy path (US1)
# ---------------------------------------------------------------------------


class TestHappyPathUpload:
    @rsps_lib.activate
    def test_file_uploaded_and_moved_to_processed(self, tmp_watch_dir: Path) -> None:
        """Drop an image → backend receives POST → file moved to processed/."""
        rsps_lib.add(rsps_lib.POST, ENDPOINT, status=200, json={"ok": True})
        processed = tmp_watch_dir / "processed"
        processed.mkdir()

        with patch("scanner.watcher.settings") as mock_cfg:
            _mock_settings(mock_cfg, tmp_watch_dir)

            from scanner.watcher import build_observer

            observer, worker = build_observer(tmp_watch_dir, processed)
            observer.start()
            worker.start()
            try:
                img = tmp_watch_dir / "scan001.jpg"
                img.write_bytes(b"\xff\xd8\xff" + b"\x00" * 50)

                moved = _wait_for(lambda: (processed / "scan001.jpg").exists())
                assert moved, "File was not moved to processed/ within timeout"
                assert not img.exists(), "Original file must be removed from watch root"
                assert len(rsps_lib.calls) == 1, "Backend must receive exactly one POST"
            finally:
                observer.stop()
                observer.join(timeout=5)
                worker.join(timeout=5)


# ---------------------------------------------------------------------------
# T017: backend unavailable — service keeps running (US2)
# ---------------------------------------------------------------------------


class TestFailurePath:
    @rsps_lib.activate
    def test_service_continues_after_upload_failure(self, tmp_watch_dir: Path) -> None:
        """After an upload failure, the observer stays alive and processes the next file."""
        processed = tmp_watch_dir / "processed"
        processed.mkdir()

        # First file → always fails
        for _ in range(3):
            rsps_lib.add(rsps_lib.POST, ENDPOINT, status=503)
        # Second file → succeeds
        rsps_lib.add(rsps_lib.POST, ENDPOINT, status=200, json={"ok": True})

        with patch("scanner.watcher.settings") as mock_cfg:
            _mock_settings(mock_cfg, tmp_watch_dir)
            # Zero wait for tests
            with patch("scanner.watcher._RETRY_WAIT", new=None):
                from scanner.watcher import build_observer

                observer, worker = build_observer(tmp_watch_dir, processed)
                observer.start()
                worker.start()
                try:
                    fail_img = tmp_watch_dir / "will_fail.jpg"
                    fail_img.write_bytes(b"\xff\xd8\xff" + b"\x00" * 10)
                    time.sleep(_SETTLE * 3)

                    ok_img = tmp_watch_dir / "will_succeed.jpg"
                    ok_img.write_bytes(b"\xff\xd8\xff" + b"\x00" * 10)

                    moved = _wait_for(lambda: (processed / "will_succeed.jpg").exists())
                    assert moved, "Second file must be processed after first fails"
                    assert fail_img.exists(), "Failed file must remain in watch root"
                    assert observer.is_alive(), "Observer must still be running after failure"
                finally:
                    observer.stop()
                    observer.join(timeout=5)
                    worker.join(timeout=5)


# ---------------------------------------------------------------------------
# T020: burst processing — all 5 files uploaded (US3)
# ---------------------------------------------------------------------------


class TestBurstProcessing:
    @rsps_lib.activate
    def test_five_simultaneous_files_all_uploaded(self, tmp_watch_dir: Path) -> None:
        """Drop 5 files rapidly; assert all 5 are uploaded and moved to processed/."""
        processed = tmp_watch_dir / "processed"
        processed.mkdir()

        for _ in range(5):
            rsps_lib.add(rsps_lib.POST, ENDPOINT, status=200, json={"ok": True})

        with patch("scanner.watcher.settings") as mock_cfg:
            _mock_settings(mock_cfg, tmp_watch_dir)

            from scanner.watcher import build_observer

            observer, worker = build_observer(tmp_watch_dir, processed)
            observer.start()
            worker.start()
            try:
                images = []
                for i in range(5):
                    img = tmp_watch_dir / f"batch_{i:03d}.jpg"
                    img.write_bytes(b"\xff\xd8\xff" + b"\x00" * 20)
                    images.append(img)

                all_moved = _wait_for(
                    lambda: len(list(processed.glob("*.jpg"))) == 5,
                    timeout=15.0,
                )
                assert all_moved, (
                    f"Expected 5 files in processed/, found {len(list(processed.glob('*.jpg')))}"
                )
                assert len(rsps_lib.calls) == 5, f"Expected 5 POSTs, got {len(rsps_lib.calls)}"
            finally:
                observer.stop()
                observer.join(timeout=5)
                worker.join(timeout=5)
