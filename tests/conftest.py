"""Shared pytest fixtures and session-level setup."""

import os
import sys
from pathlib import Path

# Set required env vars BEFORE scanner modules are imported, so Settings() doesn't fail.
os.environ.setdefault("BACKEND_UPLOAD_URL", "https://test.example.com/upload")
os.environ.setdefault("API_TOKEN", "test-token-default")

# Ensure the repo root is on sys.path so `scanner` package is importable.
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest


@pytest.fixture()
def tmp_watch_dir(tmp_path: Path) -> Path:
    """Temporary directory to use as the watch folder in tests."""
    watch = tmp_path / "watch"
    watch.mkdir()
    return watch


@pytest.fixture()
def tmp_processed_dir(tmp_watch_dir: Path) -> Path:
    """The processed/ subdirectory inside the temp watch folder."""
    processed = tmp_watch_dir / "processed"
    processed.mkdir()
    return processed
