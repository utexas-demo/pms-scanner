"""Unit tests for scanner/config.py Settings model."""

import pytest
from pydantic import ValidationError

from scanner.config import Settings


def _make_settings(**overrides: object) -> Settings:
    """Create a Settings instance with required fields + any overrides, no .env file."""
    base = {
        "backend_upload_url": "https://example.com/upload",
        "api_token": "test-token",
    }
    base.update(overrides)  # type: ignore[arg-type]
    return Settings(_env_file=None, **base)  # type: ignore[call-arg]


# T005: required fields


def test_settings_requires_backend_upload_url(monkeypatch: pytest.MonkeyPatch) -> None:
    """BACKEND_UPLOAD_URL is required; omitting it raises ValidationError."""
    monkeypatch.delenv("BACKEND_UPLOAD_URL", raising=False)
    monkeypatch.delenv("API_TOKEN", raising=False)
    with pytest.raises(ValidationError, match="backend_upload_url"):
        Settings(_env_file=None, api_token="tok")  # type: ignore[call-arg]


def test_settings_requires_api_token(monkeypatch: pytest.MonkeyPatch) -> None:
    """API_TOKEN is required; omitting it raises ValidationError."""
    monkeypatch.delenv("BACKEND_UPLOAD_URL", raising=False)
    monkeypatch.delenv("API_TOKEN", raising=False)
    with pytest.raises(ValidationError, match="api_token"):
        Settings(_env_file=None, backend_upload_url="https://x.com")  # type: ignore[call-arg]


def test_both_required_fields_missing_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """Both required fields absent raises a ValidationError listing both."""
    monkeypatch.delenv("BACKEND_UPLOAD_URL", raising=False)
    monkeypatch.delenv("API_TOKEN", raising=False)
    with pytest.raises(ValidationError) as exc_info:
        Settings(_env_file=None)  # type: ignore[call-arg]
    errors = {e["loc"][0] for e in exc_info.value.errors()}
    assert "backend_upload_url" in errors
    assert "api_token" in errors


# T005: defaults


def test_settings_default_watch_dir() -> None:
    assert _make_settings().watch_dir == "/data/incoming"


def test_settings_default_watch_recursive() -> None:
    assert _make_settings().watch_recursive is True


def test_settings_default_file_settle_seconds() -> None:
    assert _make_settings().file_settle_seconds == 0.5


def test_settings_default_upload_timeout_seconds() -> None:
    assert _make_settings().upload_timeout_seconds == 30


def test_settings_default_log_level() -> None:
    assert _make_settings().log_level == "INFO"


# T005: env var overrides


def test_settings_override_watch_dir() -> None:
    s = _make_settings(watch_dir="/tmp/scan")
    assert s.watch_dir == "/tmp/scan"


def test_settings_override_file_settle_seconds() -> None:
    s = _make_settings(file_settle_seconds=1.5)
    assert s.file_settle_seconds == 1.5


def test_settings_override_log_level() -> None:
    s = _make_settings(log_level="DEBUG")
    assert s.log_level == "DEBUG"


# T004: dashboard_port


def test_settings_default_dashboard_port() -> None:
    assert _make_settings().dashboard_port == 8080


def test_settings_override_dashboard_port() -> None:
    s = _make_settings(dashboard_port=9090)
    assert s.dashboard_port == 9090
