"""Unit tests for scanner/store.py — TDD: must FAIL before implementation."""

from __future__ import annotations

import asyncio
import threading
from datetime import UTC, datetime

import pytest

# ---------------------------------------------------------------------------
# T003: StatusStore foundational tests
# ---------------------------------------------------------------------------


class TestStatusEnum:
    def test_enum_has_four_values(self) -> None:
        from scanner.store import Status

        assert set(Status) == {Status.PENDING, Status.UPLOADING, Status.SUCCESS, Status.FAILED}

    def test_enum_values_are_lowercase_strings(self) -> None:
        from scanner.store import Status

        assert Status.PENDING.value == "pending"
        assert Status.UPLOADING.value == "uploading"
        assert Status.SUCCESS.value == "success"
        assert Status.FAILED.value == "failed"


class TestFileRecord:
    def test_has_required_fields(self) -> None:
        from scanner.store import FileRecord, Status

        now = datetime.now(UTC)
        record = FileRecord(
            id="abc-123",
            filename="scan.jpg",
            status=Status.PENDING,
            detected_at=now,
            updated_at=now,
            error_message=None,
            attempts=0,
        )
        assert record.id == "abc-123"
        assert record.filename == "scan.jpg"
        assert record.status == Status.PENDING
        assert record.error_message is None
        assert record.attempts == 0

    def test_to_json_returns_valid_json(self) -> None:
        import json

        from scanner.store import FileRecord, Status

        now = datetime.now(UTC)
        record = FileRecord(
            id="abc-123",
            filename="scan.jpg",
            status=Status.PENDING,
            detected_at=now,
            updated_at=now,
            error_message=None,
            attempts=0,
        )
        data = json.loads(record.to_json())
        assert data["id"] == "abc-123"
        assert data["filename"] == "scan.jpg"
        assert data["status"] == "pending"
        assert data["error_message"] is None
        assert data["attempts"] == 0
        assert "detected_at" in data
        assert "updated_at" in data

    def test_to_json_includes_error_message(self) -> None:
        import json

        from scanner.store import FileRecord, Status

        now = datetime.now(UTC)
        record = FileRecord(
            id="abc-123",
            filename="scan.jpg",
            status=Status.FAILED,
            detected_at=now,
            updated_at=now,
            error_message="HTTP 503 — will not retry",
            attempts=3,
        )
        data = json.loads(record.to_json())
        assert data["error_message"] == "HTTP 503 — will not retry"
        assert data["attempts"] == 3


class TestStatusStore:
    def test_add_stores_record(self) -> None:
        from scanner.store import FileRecord, Status, StatusStore

        store = StatusStore()
        now = datetime.now(UTC)
        record = FileRecord(
            id="r1",
            filename="a.jpg",
            status=Status.PENDING,
            detected_at=now,
            updated_at=now,
            error_message=None,
            attempts=0,
        )
        store.add(record)
        records = store.all()
        assert len(records) == 1
        assert records[0].id == "r1"

    def test_update_transitions_status(self) -> None:
        from scanner.store import FileRecord, Status, StatusStore

        store = StatusStore()
        now = datetime.now(UTC)
        record = FileRecord(
            id="r1",
            filename="a.jpg",
            status=Status.PENDING,
            detected_at=now,
            updated_at=now,
            error_message=None,
            attempts=0,
        )
        store.add(record)
        store.update("r1", status=Status.UPLOADING)
        records = store.all()
        assert records[0].status == Status.UPLOADING

    def test_update_refreshes_updated_at(self) -> None:
        import time

        from scanner.store import FileRecord, Status, StatusStore

        store = StatusStore()
        now = datetime.now(UTC)
        record = FileRecord(
            id="r1",
            filename="a.jpg",
            status=Status.PENDING,
            detected_at=now,
            updated_at=now,
            error_message=None,
            attempts=0,
        )
        store.add(record)
        time.sleep(0.01)
        store.update("r1", status=Status.UPLOADING)
        records = store.all()
        assert records[0].updated_at > now

    def test_all_returns_snapshot(self) -> None:
        """all() must return a copy — modifying it must not affect store internals."""
        from scanner.store import FileRecord, Status, StatusStore

        store = StatusStore()
        now = datetime.now(UTC)
        store.add(
            FileRecord(
                id="r1",
                filename="a.jpg",
                status=Status.PENDING,
                detected_at=now,
                updated_at=now,
                error_message=None,
                attempts=0,
            )
        )
        snapshot = store.all()
        snapshot.clear()
        assert len(store.all()) == 1, "Clearing snapshot must not affect store"

    def test_subscribe_returns_async_queue(self) -> None:
        from scanner.store import StatusStore

        store = StatusStore()
        q = store.subscribe()
        assert isinstance(q, asyncio.Queue)

    def test_unsubscribe_removes_queue(self) -> None:
        from scanner.store import StatusStore

        store = StatusStore()
        q = store.subscribe()
        store.unsubscribe(q)
        # Subscribing and unsubscribing should leave zero subscribers
        assert len(store._subscribers) == 0

    def test_thread_safety_add(self) -> None:
        """Multiple threads adding records concurrently must not lose records."""
        from scanner.store import FileRecord, Status, StatusStore

        store = StatusStore()
        now = datetime.now(UTC)
        errors: list[str] = []

        def add_records(start: int) -> None:
            try:
                for i in range(50):
                    store.add(
                        FileRecord(
                            id=f"r-{start}-{i}",
                            filename=f"file-{start}-{i}.jpg",
                            status=Status.PENDING,
                            detected_at=now,
                            updated_at=now,
                            error_message=None,
                            attempts=0,
                        )
                    )
            except Exception as exc:
                errors.append(str(exc))

        threads = [threading.Thread(target=add_records, args=(t,)) for t in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        assert len(store.all()) == 200

    # T013: Session history — records persist after terminal status
    def test_terminal_records_not_removed(self) -> None:
        """Records in SUCCESS or FAILED status must not be evicted from the store."""
        from scanner.store import FileRecord, Status, StatusStore

        store = StatusStore()
        now = datetime.now(UTC)
        store.add(
            FileRecord(
                id="r1",
                filename="a.jpg",
                status=Status.PENDING,
                detected_at=now,
                updated_at=now,
                error_message=None,
                attempts=0,
            )
        )
        store.update("r1", status=Status.SUCCESS, attempts=1)
        # Add a new record after terminal
        store.add(
            FileRecord(
                id="r2",
                filename="b.jpg",
                status=Status.PENDING,
                detected_at=now,
                updated_at=now,
                error_message=None,
                attempts=0,
            )
        )
        records = store.all()
        assert len(records) == 2, "Terminal record r1 must still be present"
        ids = {r.id for r in records}
        assert ids == {"r1", "r2"}

    # T015: Failed record error_message in to_json()
    def test_failed_record_to_json_includes_error(self) -> None:
        """FileRecord(status=FAILED) must include error_message in to_json() output."""
        import json

        from scanner.store import FileRecord, Status

        now = datetime.now(UTC)
        record = FileRecord(
            id="r1",
            filename="a.jpg",
            status=Status.FAILED,
            detected_at=now,
            updated_at=now,
            error_message="HTTP 401 — will not retry",
            attempts=1,
        )
        data = json.loads(record.to_json())
        assert data["error_message"] is not None
        assert "401" in data["error_message"]

    def test_update_failed_without_error_raises(self) -> None:
        """Updating to FAILED without error_message must raise ValueError."""
        from scanner.store import FileRecord, Status, StatusStore

        store = StatusStore()
        now = datetime.now(UTC)
        store.add(
            FileRecord(
                id="r1",
                filename="a.jpg",
                status=Status.PENDING,
                detected_at=now,
                updated_at=now,
                error_message=None,
                attempts=0,
            )
        )
        with pytest.raises(ValueError, match="error_message"):
            store.update("r1", status=Status.FAILED)

    def test_broadcast_to_subscribers_no_loop(self) -> None:
        """_broadcast with subscriber and no loop uses put_nowait."""
        from scanner.store import FileRecord, Status, StatusStore

        store = StatusStore()
        q = store.subscribe()
        now = datetime.now(UTC)
        store.add(
            FileRecord(
                id="r1",
                filename="a.jpg",
                status=Status.PENDING,
                detected_at=now,
                updated_at=now,
                error_message=None,
                attempts=0,
            )
        )
        # The add() call should have broadcast to the subscriber
        assert not q.empty()

    def test_set_loop_stores_reference(self) -> None:
        """set_loop must store the event loop reference."""
        from scanner.store import StatusStore

        store = StatusStore()
        loop = asyncio.new_event_loop()
        try:
            store.set_loop(loop)
            assert store._loop is loop
        finally:
            loop.close()

    def test_broadcast_with_running_loop(self) -> None:
        """_broadcast with a running loop uses run_coroutine_threadsafe."""
        from scanner.store import FileRecord, Status, StatusStore

        store = StatusStore()

        async def _run() -> None:
            store.set_loop(asyncio.get_event_loop())
            q = store.subscribe()
            now = datetime.now(UTC)
            store.add(
                FileRecord(
                    id="r1",
                    filename="a.jpg",
                    status=Status.PENDING,
                    detected_at=now,
                    updated_at=now,
                    error_message=None,
                    attempts=0,
                )
            )
            # Give the coroutine time to execute
            await asyncio.sleep(0.05)
            assert not q.empty()

        asyncio.run(_run())

    def test_update_sets_error_message_and_attempts(self) -> None:
        from scanner.store import FileRecord, Status, StatusStore

        store = StatusStore()
        now = datetime.now(UTC)
        store.add(
            FileRecord(
                id="r1",
                filename="a.jpg",
                status=Status.PENDING,
                detected_at=now,
                updated_at=now,
                error_message=None,
                attempts=0,
            )
        )
        store.update(
            "r1",
            status=Status.FAILED,
            error_message="HTTP 503",
            attempts=3,
        )
        records = store.all()
        assert records[0].error_message == "HTTP 503"
        assert records[0].attempts == 3
