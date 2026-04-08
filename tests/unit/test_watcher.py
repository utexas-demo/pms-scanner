"""Unit tests for scanner/watcher.py — TDD: new-behaviour tests must FAIL first."""

from pathlib import Path

# ---------------------------------------------------------------------------
# T008: is_image() helper
# ---------------------------------------------------------------------------


class TestIsImage:
    def test_jpg_is_supported(self, tmp_path: Path) -> None:
        from scanner.watcher import is_image

        assert is_image(tmp_path / "scan.jpg") is True

    def test_jpeg_is_supported(self, tmp_path: Path) -> None:
        from scanner.watcher import is_image

        assert is_image(tmp_path / "scan.jpeg") is True

    def test_png_is_supported(self, tmp_path: Path) -> None:
        from scanner.watcher import is_image

        assert is_image(tmp_path / "page.png") is True

    def test_gif_is_supported(self, tmp_path: Path) -> None:
        from scanner.watcher import is_image

        assert is_image(tmp_path / "anim.gif") is True

    def test_bmp_is_supported(self, tmp_path: Path) -> None:
        from scanner.watcher import is_image

        assert is_image(tmp_path / "raw.bmp") is True

    def test_tiff_is_supported(self, tmp_path: Path) -> None:
        from scanner.watcher import is_image

        assert is_image(tmp_path / "scan.tiff") is True

    def test_webp_is_supported(self, tmp_path: Path) -> None:
        from scanner.watcher import is_image

        assert is_image(tmp_path / "photo.webp") is True

    def test_uppercase_extension_is_supported(self, tmp_path: Path) -> None:
        from scanner.watcher import is_image

        assert is_image(tmp_path / "SCAN.JPG") is True

    def test_pdf_is_not_supported(self, tmp_path: Path) -> None:
        from scanner.watcher import is_image

        assert is_image(tmp_path / "doc.pdf") is False

    def test_txt_is_not_supported(self, tmp_path: Path) -> None:
        from scanner.watcher import is_image

        assert is_image(tmp_path / "notes.txt") is False

    def test_no_extension_is_not_supported(self, tmp_path: Path) -> None:
        from scanner.watcher import is_image

        assert is_image(tmp_path / "noextension") is False


# ---------------------------------------------------------------------------
# T015 (written here): deduplication seen-set
# ---------------------------------------------------------------------------


class TestDeduplication:
    def test_same_path_within_window_not_requeued(self, tmp_path: Path) -> None:
        """The same resolved path within the 2-second window must be queued only once."""
        import queue
        from unittest.mock import patch

        img = tmp_path / "scan.jpg"
        img.write_bytes(b"\xff\xd8\xff" + b"\x00" * 10)

        q: queue.Queue[Path] = queue.Queue()

        # Patch settings to use tmp_path as watch_dir
        with patch("scanner.watcher.settings") as mock_cfg:
            mock_cfg.watch_dir = str(tmp_path)
            mock_cfg.file_settle_seconds = 0.0
            mock_cfg.watch_recursive = False

            from scanner.watcher import ImageEventHandler

            handler = ImageEventHandler(upload_queue=q)

            # Simulate two rapid on_created events for the same file
            from watchdog.events import FileCreatedEvent

            handler.on_created(FileCreatedEvent(str(img)))
            handler.on_created(FileCreatedEvent(str(img)))

        # Only one item should be in the queue
        assert q.qsize() == 1, f"Expected 1 queued item, got {q.qsize()}"

    def test_different_paths_both_queued(self, tmp_path: Path) -> None:
        """Two distinct files must each be queued independently."""
        import queue
        from unittest.mock import patch

        img1 = tmp_path / "scan1.jpg"
        img2 = tmp_path / "scan2.jpg"
        img1.write_bytes(b"\xff\xd8\xff" + b"\x00" * 10)
        img2.write_bytes(b"\xff\xd8\xff" + b"\x00" * 10)

        q: queue.Queue[Path] = queue.Queue()

        with patch("scanner.watcher.settings") as mock_cfg:
            mock_cfg.watch_dir = str(tmp_path)
            mock_cfg.file_settle_seconds = 0.0
            mock_cfg.watch_recursive = False

            from scanner.watcher import ImageEventHandler

            handler = ImageEventHandler(upload_queue=q)

            from watchdog.events import FileCreatedEvent

            handler.on_created(FileCreatedEvent(str(img1)))
            handler.on_created(FileCreatedEvent(str(img2)))

        assert q.qsize() == 2, f"Expected 2 queued items, got {q.qsize()}"

    def test_processed_subdir_files_ignored(self, tmp_path: Path) -> None:
        """Files inside the processed/ subfolder must NOT be queued."""
        import queue
        from unittest.mock import patch

        processed = tmp_path / "processed"
        processed.mkdir()
        img = processed / "old.jpg"
        img.write_bytes(b"\xff\xd8\xff" + b"\x00" * 10)

        q: queue.Queue[Path] = queue.Queue()

        with patch("scanner.watcher.settings") as mock_cfg:
            mock_cfg.watch_dir = str(tmp_path)
            mock_cfg.file_settle_seconds = 0.0
            mock_cfg.watch_recursive = True

            from scanner.watcher import ImageEventHandler

            handler = ImageEventHandler(upload_queue=q)

            from watchdog.events import FileCreatedEvent

            handler.on_created(FileCreatedEvent(str(img)))

        assert q.qsize() == 0, "Files in processed/ must not be queued"


# ---------------------------------------------------------------------------
# T016: worker leaves file in place on upload failure
# ---------------------------------------------------------------------------


class TestHandlerEdgeCases:
    def test_non_image_file_not_queued(self, tmp_path: Path) -> None:
        """A .txt file detected in the watch dir must not be queued (line 208 coverage)."""
        import queue
        from unittest.mock import patch

        from watchdog.events import FileCreatedEvent

        txt = tmp_path / "notes.txt"
        txt.write_text("hello")
        q: queue.Queue[Path] = queue.Queue()

        with patch("scanner.watcher.settings") as mock_cfg:
            mock_cfg.watch_dir = str(tmp_path)
            from scanner.watcher import ImageEventHandler

            handler = ImageEventHandler(upload_queue=q)
            handler.on_created(FileCreatedEvent(str(txt)))

        assert q.qsize() == 0

    def test_on_moved_queues_image(self, tmp_path: Path) -> None:
        """A file moved into the watch dir triggers on_moved and is queued (225-228 coverage)."""
        import queue
        from unittest.mock import patch

        from watchdog.events import FileMovedEvent

        img = tmp_path / "moved.jpg"
        img.write_bytes(b"\xff\xd8\xff" + b"\x00" * 10)
        q: queue.Queue[Path] = queue.Queue()

        with patch("scanner.watcher.settings") as mock_cfg:
            mock_cfg.watch_dir = str(tmp_path)
            from scanner.watcher import ImageEventHandler

            handler = ImageEventHandler(upload_queue=q)
            handler.on_moved(FileMovedEvent("/tmp/src.jpg", str(img)))

        assert q.qsize() == 1


class TestWorkerFileDisposition:
    def test_file_moved_to_processed_on_success(
        self, tmp_watch_dir: Path, tmp_processed_dir: Path
    ) -> None:
        """After a successful upload, the file must exist in processed/ and not in watch root."""
        from unittest.mock import patch

        from scanner.watcher import UploadResult

        img = tmp_watch_dir / "scan.jpg"
        img.write_bytes(b"\xff\xd8\xff" + b"\x00" * 10)

        success_result = UploadResult(
            success=True,
            file_path=img,
            http_status=200,
            destination_path=tmp_processed_dir / "scan.jpg",
        )

        with (
            patch("scanner.watcher.upload_image", return_value=success_result),
            patch("scanner.watcher.settings") as mock_cfg,
        ):
            mock_cfg.watch_dir = str(tmp_watch_dir)
            mock_cfg.file_settle_seconds = 0.0

            from scanner.watcher import process_file

            process_file(img, tmp_watch_dir, tmp_processed_dir)

        assert (tmp_processed_dir / "scan.jpg").exists(), "File must be in processed/ after success"
        assert not img.exists(), "File must not remain in watch root after success"

    def test_file_disappeared_before_upload_is_skipped(
        self, tmp_watch_dir: Path, tmp_processed_dir: Path
    ) -> None:
        """File deleted before upload: process_file logs warning and returns (168-169 coverage)."""
        from unittest.mock import patch

        from scanner.watcher import process_file

        img = tmp_watch_dir / "ghost.jpg"
        # Do NOT create the file — it's already gone

        with patch("scanner.watcher.settings") as mock_cfg:
            mock_cfg.watch_dir = str(tmp_watch_dir)
            mock_cfg.file_settle_seconds = 0.0
            # Should not raise, just log and return
            process_file(img, tmp_watch_dir, tmp_processed_dir)

        # No file should have been created in processed/
        assert not (tmp_processed_dir / "ghost.jpg").exists()

    def test_file_stays_in_watch_root_on_failure(
        self, tmp_watch_dir: Path, tmp_processed_dir: Path
    ) -> None:
        """After a failed upload, the file must remain in the watch root unchanged."""
        from unittest.mock import patch

        from scanner.watcher import UploadResult

        img = tmp_watch_dir / "scan.jpg"
        img.write_bytes(b"\xff\xd8\xff" + b"\x00" * 10)

        failure_result = UploadResult(
            success=False,
            file_path=img,
            error_message="Connection refused",
        )

        with (
            patch("scanner.watcher.upload_image", return_value=failure_result),
            patch("scanner.watcher.settings") as mock_cfg,
        ):
            mock_cfg.watch_dir = str(tmp_watch_dir)
            mock_cfg.file_settle_seconds = 0.0

            from scanner.watcher import process_file

            process_file(img, tmp_watch_dir, tmp_processed_dir)

        assert img.exists(), "File must remain in watch root after upload failure"
        assert not (tmp_processed_dir / "scan.jpg").exists(), (
            "File must NOT be in processed/ after failure"
        )
