"""Unit tests for graceful shutdown in scanner/__main__.py — T035."""
import os
import signal
from unittest.mock import MagicMock, patch


def test_sigterm_stops_scheduler():
    """SIGTERM signal calls scheduler.shutdown(wait=True)."""
    with patch.dict(os.environ, {"BACKEND_BASE_URL": "http://x", "API_TOKEN": "t"}):
        import importlib

        import scanner.__main__ as main_mod
        importlib.reload(main_mod)

        mock_scheduler = MagicMock()
        mock_scheduler.running = True
        main_mod.scheduler = mock_scheduler

        with pytest.raises(SystemExit):
            main_mod._shutdown(signal.SIGTERM, None)

        mock_scheduler.shutdown.assert_called_once_with(wait=True)


def test_sigint_stops_scheduler():
    """SIGINT signal calls scheduler.shutdown(wait=True)."""
    with patch.dict(os.environ, {"BACKEND_BASE_URL": "http://x", "API_TOKEN": "t"}):
        import importlib

        import scanner.__main__ as main_mod
        importlib.reload(main_mod)

        mock_scheduler = MagicMock()
        mock_scheduler.running = True
        main_mod.scheduler = mock_scheduler

        with pytest.raises(SystemExit):
            main_mod._shutdown(signal.SIGINT, None)

        mock_scheduler.shutdown.assert_called_once_with(wait=True)


def test_shutdown_no_scheduler_still_exits():
    """_shutdown exits cleanly even when scheduler is None."""
    with patch.dict(os.environ, {"BACKEND_BASE_URL": "http://x", "API_TOKEN": "t"}):
        import importlib

        import scanner.__main__ as main_mod
        importlib.reload(main_mod)
        main_mod.scheduler = None

        with pytest.raises(SystemExit):
            main_mod._shutdown(signal.SIGTERM, None)


import pytest  # noqa: E402 — import after test functions to avoid affecting test collection order
