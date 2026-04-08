"""Contract tests for the backend upload request shape — per contracts/backend-upload.md.

TDD: these must FAIL before upload_image() is refactored.
"""

from pathlib import Path
from unittest.mock import patch

import responses as rsps_lib

ENDPOINT = "https://api.example.com/v1/upload"
TOKEN = "test-token-abc"


@rsps_lib.activate
def test_upload_sends_bearer_auth_header(tmp_path: Path) -> None:
    """upload_image() MUST include Authorization: Bearer {token} header."""
    img = tmp_path / "scan.jpg"
    img.write_bytes(b"\xff\xd8\xff" + b"\x00" * 10)

    rsps_lib.add(rsps_lib.POST, ENDPOINT, status=200, json={"ok": True})

    with (
        patch("scanner.watcher.settings") as mock_cfg,
    ):
        mock_cfg.backend_upload_url = ENDPOINT
        mock_cfg.api_token = TOKEN
        mock_cfg.upload_timeout_seconds = 5
        mock_cfg.watch_dir = str(tmp_path)

        from scanner.watcher import upload_image

        upload_image(img)

    assert len(rsps_lib.calls) == 1
    auth = rsps_lib.calls[0].request.headers.get("Authorization", "")
    assert auth == f"Bearer {TOKEN}", f"Expected Bearer {TOKEN}, got {auth!r}"


@rsps_lib.activate
def test_upload_sends_file_multipart_part(tmp_path: Path) -> None:
    """upload_image() MUST send a 'file' multipart part with filename and content."""
    img = tmp_path / "photo.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 20)

    rsps_lib.add(rsps_lib.POST, ENDPOINT, status=200, json={"ok": True})

    with patch("scanner.watcher.settings") as mock_cfg:
        mock_cfg.backend_upload_url = ENDPOINT
        mock_cfg.api_token = TOKEN
        mock_cfg.upload_timeout_seconds = 5
        mock_cfg.watch_dir = str(tmp_path)

        from scanner.watcher import upload_image

        upload_image(img)

    body = rsps_lib.calls[0].request.body
    assert b"photo.png" in body, "Filename must be present in multipart body"
    assert b"image/png" in body, "MIME type must be present in multipart body"


@rsps_lib.activate
def test_upload_sends_folder_field(tmp_path: Path) -> None:
    """upload_image() MUST send a 'folder' field with the relative sub-path."""
    sub = tmp_path / "patient-42"
    sub.mkdir()
    img = sub / "page1.jpg"
    img.write_bytes(b"\xff\xd8\xff" + b"\x00" * 10)

    rsps_lib.add(rsps_lib.POST, ENDPOINT, status=200, json={"ok": True})

    with patch("scanner.watcher.settings") as mock_cfg:
        mock_cfg.backend_upload_url = ENDPOINT
        mock_cfg.api_token = TOKEN
        mock_cfg.upload_timeout_seconds = 5
        mock_cfg.watch_dir = str(tmp_path)

        from scanner.watcher import upload_image

        upload_image(img)

    body = rsps_lib.calls[0].request.body
    assert b"patient-42" in body, "Relative folder path must be in multipart body"
