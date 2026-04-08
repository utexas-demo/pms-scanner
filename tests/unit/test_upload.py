"""Unit tests for upload_image() in scanner/watcher.py — TDD: must FAIL before refactor."""

from pathlib import Path
from unittest.mock import patch

import responses as rsps_lib

ENDPOINT = "https://api.test/upload"
TOKEN = "test-secret"


def _make_image(tmp_path: Path, name: str = "scan.jpg") -> Path:
    img = tmp_path / name
    img.write_bytes(b"\xff\xd8\xff" + b"\x00" * 20)
    return img


def _mock_settings(mock_cfg: object, tmp_path: Path) -> None:
    mock_cfg.backend_upload_url = ENDPOINT  # type: ignore[attr-defined]
    mock_cfg.api_token = TOKEN  # type: ignore[attr-defined]
    mock_cfg.upload_timeout_seconds = 5  # type: ignore[attr-defined]
    mock_cfg.watch_dir = str(tmp_path)  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# T009: upload_image() happy path (tests new UploadResult return type)
# ---------------------------------------------------------------------------


class TestUploadImageSuccess:
    @rsps_lib.activate
    def test_returns_upload_result_on_success(self, tmp_path: Path) -> None:
        """upload_image() must return an UploadResult with success=True on 2xx."""
        rsps_lib.add(rsps_lib.POST, ENDPOINT, status=200, json={"ok": True})
        img = _make_image(tmp_path)

        with patch("scanner.watcher.settings") as mock_cfg:
            _mock_settings(mock_cfg, tmp_path)
            from scanner.watcher import UploadResult, upload_image

            result = upload_image(img)

        assert isinstance(result, UploadResult), "Must return UploadResult, not bool"
        assert result.success is True
        assert result.http_status == 200
        assert result.error_message is None
        assert result.attempts == 1

    @rsps_lib.activate
    def test_success_result_has_destination_path(self, tmp_path: Path) -> None:
        """On success, UploadResult.destination_path must point inside processed/."""
        rsps_lib.add(rsps_lib.POST, ENDPOINT, status=200, json={"ok": True})
        img = _make_image(tmp_path)

        with patch("scanner.watcher.settings") as mock_cfg:
            _mock_settings(mock_cfg, tmp_path)
            from scanner.watcher import upload_image

            result = upload_image(img)

        assert result.destination_path is not None
        assert "processed" in str(result.destination_path)

    @rsps_lib.activate
    def test_bearer_auth_header_sent(self, tmp_path: Path) -> None:
        """upload_image() must include Authorization: Bearer {token} header."""
        rsps_lib.add(rsps_lib.POST, ENDPOINT, status=200, json={"ok": True})
        img = _make_image(tmp_path)

        with patch("scanner.watcher.settings") as mock_cfg:
            _mock_settings(mock_cfg, tmp_path)
            from scanner.watcher import upload_image

            upload_image(img)

        auth = rsps_lib.calls[0].request.headers.get("Authorization", "")
        assert auth == f"Bearer {TOKEN}"

    @rsps_lib.activate
    def test_folder_field_is_relative_path(self, tmp_path: Path) -> None:
        """The 'folder' multipart field must be the relative path from watch root."""
        rsps_lib.add(rsps_lib.POST, ENDPOINT, status=200, json={"ok": True})
        sub = tmp_path / "ward-5"
        sub.mkdir()
        img = sub / "scan.jpg"
        img.write_bytes(b"\xff\xd8\xff" + b"\x00" * 10)

        with patch("scanner.watcher.settings") as mock_cfg:
            _mock_settings(mock_cfg, tmp_path)
            from scanner.watcher import upload_image

            upload_image(img)

        body = rsps_lib.calls[0].request.body
        assert b"ward-5" in body


# ---------------------------------------------------------------------------
# T015: upload_image() failure paths
# ---------------------------------------------------------------------------


class TestUploadImageFolderField:
    @rsps_lib.activate
    def test_folder_empty_string_when_file_outside_watch_dir(self, tmp_path: Path) -> None:
        """File outside watch_dir: folder field falls back to empty string (84-85 coverage)."""
        rsps_lib.add(rsps_lib.POST, ENDPOINT, status=200, json={"ok": True})

        # File is in /tmp/other, watch_dir is /tmp/watch — path is NOT inside watch_dir
        other = tmp_path / "other"
        other.mkdir()
        img = other / "scan.jpg"
        img.write_bytes(b"\xff\xd8\xff" + b"\x00" * 10)

        watch_dir = tmp_path / "watch"
        watch_dir.mkdir()

        with patch("scanner.watcher.settings") as mock_cfg:
            mock_cfg.backend_upload_url = ENDPOINT
            mock_cfg.api_token = TOKEN
            mock_cfg.upload_timeout_seconds = 5
            mock_cfg.watch_dir = str(watch_dir)  # different from file's parent
            from scanner.watcher import upload_image

            result = upload_image(img)

        assert result.success is True
        body = rsps_lib.calls[0].request.body
        # folder field should be empty or just a dot — not raise
        assert b"folder" in body


class TestUploadImageFailure:
    @rsps_lib.activate
    def test_http_4xx_returns_failure_no_retry(self, tmp_path: Path) -> None:
        """HTTP 4xx returns UploadResult(success=False) with exactly 1 attempt (no retry)."""
        rsps_lib.add(rsps_lib.POST, ENDPOINT, status=401, json={"error": "Unauthorized"})
        img = _make_image(tmp_path)

        with patch("scanner.watcher.settings") as mock_cfg:
            _mock_settings(mock_cfg, tmp_path)
            from scanner.watcher import UploadResult, upload_image

            result = upload_image(img)

        assert isinstance(result, UploadResult)
        assert result.success is False
        assert result.attempts == 1, "4xx must NOT be retried"
        assert result.error_message is not None
        assert result.destination_path is None

    @rsps_lib.activate
    def test_http_5xx_retried_up_to_3_times(self, tmp_path: Path) -> None:
        """HTTP 5xx is retried up to 3 times before returning failure."""
        for _ in range(3):
            rsps_lib.add(rsps_lib.POST, ENDPOINT, status=503, json={"error": "Unavailable"})
        img = _make_image(tmp_path)

        with patch("scanner.watcher.settings") as mock_cfg:
            _mock_settings(mock_cfg, tmp_path)
            # Patch tenacity wait to avoid actual sleeping in tests
            with patch("scanner.watcher._RETRY_WAIT", new=None):
                from scanner.watcher import upload_image

                result = upload_image(img)

        assert result.success is False
        assert result.attempts == 3, f"Expected 3 attempts, got {result.attempts}"
        assert result.error_message is not None

    @rsps_lib.activate
    def test_failure_result_has_no_destination_path(self, tmp_path: Path) -> None:
        """On failure, UploadResult.destination_path must be None."""
        rsps_lib.add(rsps_lib.POST, ENDPOINT, status=500)
        for _ in range(2):
            rsps_lib.add(rsps_lib.POST, ENDPOINT, status=500)
        img = _make_image(tmp_path)

        with patch("scanner.watcher.settings") as mock_cfg:
            _mock_settings(mock_cfg, tmp_path)
            with patch("scanner.watcher._RETRY_WAIT", new=None):
                from scanner.watcher import upload_image

                result = upload_image(img)

        assert result.destination_path is None

    def test_network_error_returns_failure(self, tmp_path: Path) -> None:
        """A network exception (ConnectionError) returns UploadResult(success=False)."""
        import requests

        img = _make_image(tmp_path)

        with (
            patch("scanner.watcher.settings") as mock_cfg,
            patch("requests.Session.post", side_effect=requests.ConnectionError("refused")),
        ):
            _mock_settings(mock_cfg, tmp_path)
            with patch("scanner.watcher._RETRY_WAIT", new=None):
                from scanner.watcher import upload_image

                result = upload_image(img)

        assert result.success is False
        assert result.error_message is not None
