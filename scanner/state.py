"""
Shared in-memory state for the batch runner and the dashboard.

004 adds the per-(machine, environment) :class:`BatchRunState` container
(data-model.md) plus :func:`make_logger`, an env/machine-tagging,
secret-redacting logger adapter (Constitution Principle IV). The legacy
single-env :class:`AppState` / :class:`RunRecord` remain until batch.py and
dashboard.py migrate (tasks T020/T022/T046/T048).
"""

from __future__ import annotations

import asyncio
import logging
import re
import threading
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import uuid4

from .machine import MachineIdentity
from .ntp import ClockSyncEvent

__all__ = [
    "AppState",
    "BatchRunState",
    "ClockSyncEvent",
    "ErrorRecord",
    "FileResult",
    "PageResult",
    "PerEnvRunState",
    "RunRecord",
    "app_state",
    "make_logger",
]


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
class RunRecord:
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
        self.current_run: RunRecord | None = None  # most recent active run
        self.last_run: RunRecord | None = None
        self.active_runs: dict[str, RunRecord] = {}
        self.history: list[RunRecord] = []  # completed runs, newest first
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


def _run_to_dict(run: RunRecord | None) -> dict[str, Any] | None:
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


# ===========================================================================
# 004 — per-(machine, environment) state container (data-model.md)
# ===========================================================================


@dataclass(slots=True)
class ErrorRecord:
    """One environment-scoped error, surfaced on the dashboard."""

    filename: str
    message: str
    page_num: int | None = None
    at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(slots=True)
class PerEnvRunState:
    """Counters + current activity for one environment on this machine."""

    machine: str
    environment: str
    current_file: str | None = None
    current_page: int = 0
    total_pages: int = 0
    files_processed: int = 0
    pages_uploaded: int = 0
    errors: list[ErrorRecord] = field(default_factory=list)
    last_run_started_at: datetime | None = None
    last_run_finished_at: datetime | None = None


_DRIFT_WARNING_OUTCOMES = frozenset(
    {"drift_uncorrected", "unreachable", "rejected_kod"}
)


class BatchRunState:
    """In-memory dashboard state keyed by ``(machine, environment)``.

    A single :class:`threading.RLock` guards every counter mutation so
    concurrent per-env scheduler jobs never lose updates. ``recent_clock_sync``
    / ``last_drift_warning`` are plain attributes (assigned atomically) so this
    object can also serve as a :class:`scanner.ntp._DriftSink`.
    """

    def __init__(
        self, machine: MachineIdentity, env_names: Iterable[str]
    ) -> None:
        self.machine = machine
        self.per_env: dict[str, PerEnvRunState] = {
            name: PerEnvRunState(machine=machine.name, environment=name)
            for name in env_names
        }
        self.recent_clock_sync: ClockSyncEvent | None = None
        self.last_drift_warning: ClockSyncEvent | None = None
        self._lock = threading.RLock()

    def env(self, name: str) -> PerEnvRunState:
        """Return the per-env state, raising ``KeyError`` if unconfigured."""
        return self.per_env[name]

    def add_pages_uploaded(self, name: str, n: int = 1) -> None:
        with self._lock:
            self.per_env[name].pages_uploaded += n

    def add_files_processed(self, name: str, n: int = 1) -> None:
        with self._lock:
            self.per_env[name].files_processed += n

    def add_error(self, name: str, record: ErrorRecord) -> None:
        with self._lock:
            self.per_env[name].errors.append(record)

    def set_current(
        self,
        name: str,
        *,
        current_file: str | None = None,
        current_page: int | None = None,
        total_pages: int | None = None,
    ) -> None:
        with self._lock:
            st = self.per_env[name]
            if current_file is not None:
                st.current_file = current_file
            if current_page is not None:
                st.current_page = current_page
            if total_pages is not None:
                st.total_pages = total_pages

    def mark_run_started(self, name: str, when: datetime) -> None:
        with self._lock:
            self.per_env[name].last_run_started_at = when

    def mark_run_finished(self, name: str, when: datetime) -> None:
        with self._lock:
            self.per_env[name].last_run_finished_at = when

    def record_clock_sync(self, event: ClockSyncEvent) -> None:
        with self._lock:
            self.recent_clock_sync = event
            if event.outcome in _DRIFT_WARNING_OUTCOMES:
                self.last_drift_warning = event


# ===========================================================================
# 004 — env/machine-tagging, secret-redacting logger (Constitution IV)
# ===========================================================================


class _RedactingFilter(logging.Filter):
    """Masks registered secret substrings in the final formatted message."""

    def __init__(self, secrets: Iterable[str]) -> None:
        super().__init__()
        self._patterns = [
            re.compile(re.escape(s)) for s in secrets if s and s.strip()
        ]

    def filter(self, record: logging.LogRecord) -> bool:
        if not self._patterns:
            return True
        message = record.getMessage()
        for pat in self._patterns:
            message = pat.sub("***", message)
        record.msg = message
        record.args = None
        return True


class _EnvMachineAdapter(logging.LoggerAdapter):  # type: ignore[type-arg]
    """Prefixes every message with ``[machine=… env=…]``."""

    def process(
        self, msg: str, kwargs: Any
    ) -> tuple[str, Any]:
        extra = self.extra or {}
        machine = extra.get("machine", "?")
        env = extra.get("env", "?")
        return f"[machine={machine} env={env}] {msg}", kwargs


def make_logger(
    name: str,
    *,
    machine: str,
    env: str,
    secrets: Iterable[str] = (),
) -> logging.LoggerAdapter:  # type: ignore[type-arg]
    """Build an env/machine-tagged adapter with secret redaction.

    Every emitted record is prefixed with ``[machine=… env=…]`` and any
    registered secret value (e.g. an API token) is masked to ``***``.
    """
    base = logging.getLogger(name)
    secret_list = [s for s in secrets if s and s.strip()]
    if secret_list and not any(
        isinstance(f, _RedactingFilter) for f in base.filters
    ):
        base.addFilter(_RedactingFilter(secret_list))
    return _EnvMachineAdapter(base, {"machine": machine, "env": env})
