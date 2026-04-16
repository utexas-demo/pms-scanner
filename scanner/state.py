"""
Shared in-memory state for the batch runner and the dashboard.

All mutations must be performed under AppState._lock.  The lock is never held
across a network call.
"""

import asyncio
import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import uuid4


@dataclass
class PageResult:
    """Outcome of uploading a single PDF page."""

    page_num: int
    total_pages: int
    rotation_applied: int  # degrees: 0, 90, 180, 270
    upload_success: bool
    orientation_uncertain: bool = False
    error: str | None = None


@dataclass
class FileResult:
    """Outcome of processing a single PDF file."""

    filename: str
    total_pages: int
    pages: list[PageResult] = field(default_factory=list)
    status: Literal["pending", "in_progress", "completed", "failed"] = "pending"
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    completed_at: datetime | None = None


@dataclass
class BatchRunState:
    """Represents a single scheduled batch run."""

    run_id: str = field(default_factory=lambda: str(uuid4()))
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    completed_at: datetime | None = None
    files: list[FileResult] = field(default_factory=list)
    status: Literal["running", "completed", "failed"] = "running"
    recovered_files: list[str] = field(default_factory=list)


class AppState:
    """
    Top-level singleton shared between the batch runner and the dashboard.

    All field mutations must be performed under _lock.  The lock must NOT be
    held across any network or I/O call.
    """

    HISTORY_LIMIT = 50

    def __init__(self) -> None:
        self._lock: threading.Lock = threading.Lock()
        self.current_run: BatchRunState | None = None  # most recent active run
        self.last_run: BatchRunState | None = None
        self.active_runs: dict[str, BatchRunState] = {}
        self.history: list[BatchRunState] = []  # completed runs, newest first
        # asyncio event loop reference — set in __main__.py before uvicorn starts
        self.loop: asyncio.AbstractEventLoop | None = None
        # Queue polled by the SSE endpoint
        self.event_queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()

    def emit_event(self, event: dict[str, Any]) -> None:
        """
        Thread-safe push of an event dict onto the asyncio queue.

        Safe to call from the scheduler thread.  If no event loop is wired up
        yet (e.g. during tests) the event is silently dropped.
        """
        if self.loop is not None and not self.loop.is_closed():
            self.loop.call_soon_threadsafe(self.event_queue.put_nowait, event)

    def to_status_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable snapshot of all active + recent runs."""
        with self._lock:
            return {
                "current_run": _run_to_dict(self.current_run),
                "last_run": _run_to_dict(self.last_run),
                "active_runs": [
                    _run_to_dict(r) for r in self.active_runs.values()
                ],
                "history": [_run_to_dict(r) for r in self.history],
            }


# ---------------------------------------------------------------------------
# Serialisation helpers
# ---------------------------------------------------------------------------


def _page_to_dict(p: PageResult) -> dict[str, Any]:
    return {
        "page_num": p.page_num,
        "total_pages": p.total_pages,
        "rotation_applied": p.rotation_applied,
        "orientation_uncertain": p.orientation_uncertain,
        "upload_success": p.upload_success,
        "error": p.error,
    }


def _file_to_dict(f: FileResult) -> dict[str, Any]:
    return {
        "filename": f.filename,
        "total_pages": f.total_pages,
        "status": f.status,
        "started_at": f.started_at.isoformat(),
        "completed_at": f.completed_at.isoformat() if f.completed_at else None,
        "pages": [_page_to_dict(p) for p in f.pages],
    }


def _run_to_dict(run: BatchRunState | None) -> dict[str, Any] | None:
    if run is None:
        return None
    return {
        "run_id": run.run_id,
        "status": run.status,
        "started_at": run.started_at.isoformat(),
        "completed_at": run.completed_at.isoformat() if run.completed_at else None,
        "files": [_file_to_dict(f) for f in run.files],
        "recovered_files": run.recovered_files,
    }


# Module-level singleton
app_state = AppState()
