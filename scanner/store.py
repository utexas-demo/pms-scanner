"""
In-memory status store for upload progress tracking.

Thread-safe singleton shared between the scanner worker thread and the FastAPI
event loop. Publishes SSE events to connected browser clients.
"""

from __future__ import annotations

import asyncio
import contextlib
import enum
import json
import logging
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)


class Status(enum.Enum):
    """Upload lifecycle stages — values serialise as lowercase strings."""

    PENDING = "pending"
    UPLOADING = "uploading"
    SUCCESS = "success"
    FAILED = "failed"


@dataclass
class FileRecord:
    """One file's upload lifecycle within a session."""

    id: str
    filename: str
    status: Status
    detected_at: datetime
    updated_at: datetime
    error_message: str | None
    attempts: int

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable dictionary."""
        return {
            "id": self.id,
            "filename": self.filename,
            "status": self.status.value,
            "detected_at": self.detected_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "error_message": self.error_message,
            "attempts": self.attempts,
        }

    def to_json(self) -> str:
        """Return a single-line JSON string for SSE payloads."""
        return json.dumps(self.to_dict())


class StatusStore:
    """Thread-safe in-memory store for file upload status records.

    The scanner worker thread calls :meth:`add` and :meth:`update` (behind a
    :class:`threading.Lock`).  The FastAPI SSE endpoint calls
    :meth:`subscribe` / :meth:`unsubscribe` to receive push notifications via
    :class:`asyncio.Queue`.
    """

    def __init__(self) -> None:
        self._records: dict[str, FileRecord] = {}
        self._lock = threading.Lock()
        self._subscribers: list[asyncio.Queue[str]] = []
        self._loop: asyncio.AbstractEventLoop | None = None

    # -- public API ----------------------------------------------------------

    def add(self, record: FileRecord) -> None:
        """Store a new :class:`FileRecord` and broadcast an SSE event."""
        with self._lock:
            self._records[record.id] = record
        self._broadcast(record.to_json())

    def update(
        self,
        record_id: str,
        *,
        status: Status,
        error_message: str | None = None,
        attempts: int | None = None,
    ) -> None:
        """Transition *record_id* to *status* and broadcast an SSE event."""
        if status == Status.FAILED and error_message is None:
            raise ValueError("error_message is required when status is FAILED")
        with self._lock:
            record = self._records[record_id]
            record.status = status
            record.updated_at = datetime.now(UTC)
            if error_message is not None:
                record.error_message = error_message
            if attempts is not None:
                record.attempts = attempts
            payload = record.to_json()
        self._broadcast(payload)

    def all(self) -> list[FileRecord]:
        """Return a snapshot (shallow copy) of all records."""
        with self._lock:
            return list(self._records.values())

    def subscribe(self) -> asyncio.Queue[str]:
        """Register a new SSE subscriber queue."""
        q: asyncio.Queue[str] = asyncio.Queue()
        self._subscribers.append(q)
        logger.debug("SSE subscriber added (total: %d)", len(self._subscribers))
        return q

    def unsubscribe(self, q: asyncio.Queue[str]) -> None:
        """Remove a subscriber queue."""
        with contextlib.suppress(ValueError):
            self._subscribers.remove(q)
        logger.debug("SSE subscriber removed (total: %d)", len(self._subscribers))

    def set_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """Store a reference to the uvicorn event loop for cross-thread push."""
        self._loop = loop

    # -- internal ------------------------------------------------------------

    def _broadcast(self, payload: str) -> None:
        """Push *payload* to all subscriber queues.

        If an event loop is set, uses :func:`asyncio.run_coroutine_threadsafe`
        for thread-safe delivery.  Otherwise falls back to direct
        :meth:`asyncio.Queue.put_nowait` (suitable for single-threaded tests).
        """
        if not self._subscribers:
            return

        async def _push() -> None:
            for q in list(self._subscribers):
                await q.put(payload)

        if self._loop is not None and self._loop.is_running():
            asyncio.run_coroutine_threadsafe(_push(), self._loop)
        else:
            for q in list(self._subscribers):
                q.put_nowait(payload)


status_store = StatusStore()
