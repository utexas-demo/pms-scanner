"""Unit tests for scanner/config.py — T005."""
import os
from pathlib import Path
from unittest.mock import patch


def test_cron_interval_seconds_default():
    """cron_interval_seconds defaults to 60."""
    with patch.dict(os.environ, {"BACKEND_BASE_URL": "http://x", "API_TOKEN": "t"}, clear=False):
        from config import Settings
        s = Settings()
        assert s.cron_interval_seconds == 60


def test_dashboard_port_default():
    """dashboard_port defaults to 8080."""
    with patch.dict(os.environ, {"BACKEND_BASE_URL": "http://x", "API_TOKEN": "t"}, clear=False):
        from config import Settings
        s = Settings()
        assert s.dashboard_port == 8080


def test_file_settle_seconds_default():
    """file_settle_seconds defaults to 10.0."""
    with patch.dict(os.environ, {"BACKEND_BASE_URL": "http://x", "API_TOKEN": "t"}, clear=False):
        from config import Settings
        s = Settings()
        assert s.file_settle_seconds == 10.0


def test_inprogress_dir_derived_from_watch_dir():
    """inprogress_dir is watch_dir/in-progress."""
    with patch.dict(
        os.environ,
        {"BACKEND_BASE_URL": "http://x", "API_TOKEN": "t", "WATCH_DIR": "/tmp/aria"},
        clear=False,
    ):
        from config import Settings
        s = Settings()
        assert s.inprogress_dir == Path("/tmp/aria/in-progress")


def test_processed_dir_derived_from_watch_dir():
    """processed_dir is watch_dir/processed."""
    with patch.dict(
        os.environ,
        {"BACKEND_BASE_URL": "http://x", "API_TOKEN": "t", "WATCH_DIR": "/tmp/aria"},
        clear=False,
    ):
        from config import Settings
        s = Settings()
        assert s.processed_dir == Path("/tmp/aria/processed")


def test_upload_max_retries_default():
    """upload_max_retries defaults to 3."""
    with patch.dict(os.environ, {"BACKEND_BASE_URL": "http://x", "API_TOKEN": "t"}, clear=False):
        from config import Settings
        s = Settings()
        assert s.upload_max_retries == 3
