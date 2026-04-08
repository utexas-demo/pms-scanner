"""Integration tests for the upload progress dashboard (US1).

TDD: must FAIL before scanner/api.py and watcher-store integration are implemented.
"""

import time
from pathlib import Path
from unittest.mock import patch

import responses as rsps_lib

ENDPOINT = "https://api.test/upload"
TOKEN = "integration-token"
_SETTLE = 0.05
_TIMEOUT = 8.0


def _mock_settings(mock_cfg: object, watch_dir: Path) -> None:
    mock_cfg.backend_upload_url = ENDPOINT  # type: ignore[attr-defined]
    mock_cfg.api_token = TOKEN  # type: ignore[attr-defined]
    mock_cfg.upload_timeout_seconds = 5  # type: ignore[attr-defined]
    mock_cfg.watch_dir = str(watch_dir)  # type: ignore[attr-defined]
    mock_cfg.file_settle_seconds = _SETTLE  # type: ignore[attr-defined]
    mock_cfg.watch_recursive = True  # type: ignore[attr-defined]
    mock_cfg.log_level = "DEBUG"  # type: ignore[attr-defined]
    mock_cfg.dashboard_port = 18080  # type: ignore[attr-defined]


def _wait_for(condition: object, timeout: float = _TIMEOUT) -> bool:
    """Poll condition() until True or timeout (seconds)."""
    from collections.abc import Callable

    assert callable(condition)
    fn: Callable[[], bool] = condition
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if fn():
            return True
        time.sleep(0.1)
    return False


# ---------------------------------------------------------------------------
# T009: Scanner → StatusStore integration (US1)
# ---------------------------------------------------------------------------


class TestDashboardIntegration:
    @rsps_lib.activate
    def test_file_progresses_through_status_store(self, tmp_path: Path) -> None:
        """Drop image → store records pending→uploading→success transitions."""
        rsps_lib.add(rsps_lib.POST, ENDPOINT, status=200, json={"ok": True})
        watch_dir = tmp_path / "watch"
        watch_dir.mkdir()
        processed = watch_dir / "processed"
        processed.mkdir()

        from scanner.store import StatusStore

        store = StatusStore()

        with (
            patch("scanner.watcher.settings") as mock_cfg,
            patch("scanner.watcher.status_store", store),
        ):
            _mock_settings(mock_cfg, watch_dir)

            from scanner.watcher import build_observer

            observer, worker = build_observer(watch_dir, processed)
            observer.start()
            worker.start()
            try:
                img = watch_dir / "dashboard_test.jpg"
                img.write_bytes(b"\xff\xd8\xff" + b"\x00" * 50)

                # Wait for the record to reach SUCCESS
                def _is_done() -> bool:
                    records = store.all()
                    return any(r.status.value == "success" for r in records)

                done = _wait_for(_is_done)
                assert done, "File status did not reach SUCCESS within timeout"

                records = store.all()
                assert len(records) == 1
                r = records[0]
                assert r.filename == "dashboard_test.jpg"
                assert r.status.value == "success"
                assert (processed / "dashboard_test.jpg").exists()
            finally:
                observer.stop()
                observer.join(timeout=5)
                worker.join(timeout=5)
