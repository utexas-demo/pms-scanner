"""NTP offset measurement, startup gate, and recurring drift monitor (004).

The main process stays unprivileged: it only *measures* offset via
``ntplib``. Clock correction is delegated to an out-of-band privileged
helper (research.md §3). Obviously-wrong responses (kiss-of-death
stratum 16, or an offset magnitude exceeding one day) are rejected.
"""

from __future__ import annotations

import logging
import socket
import subprocess
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal, Protocol

import ntplib

logger = logging.getLogger(__name__)

# Reject any response whose offset magnitude exceeds one day.
_MAX_PLAUSIBLE_OFFSET_SECONDS = 86_400.0
_KISS_OF_DEATH_STRATUM = 16

NTPOutcome = Literal["ok", "rejected_kod"]

ClockSyncOutcome = Literal[
    "ok", "drift_corrected", "drift_uncorrected", "unreachable", "rejected_kod"
]

# Outcomes that represent a problem an operator should see surfaced.
_WARNING_OUTCOMES: frozenset[str] = frozenset(
    {"drift_uncorrected", "unreachable", "rejected_kod"}
)


class NTPUnreachableError(RuntimeError):
    """The NTP source could not be reached / returned no usable response."""


class NTPStartupError(RuntimeError):
    """Startup gate failed — the process must refuse to start (FR-022/024)."""


class _Measurer(Protocol):
    source: str

    def measure(self) -> NTPMeasurement: ...


@dataclass(frozen=True, slots=True)
class NTPMeasurement:
    """One offset measurement against the configured NTP source."""

    source: str
    offset_seconds: float
    measured_at: datetime
    outcome: NTPOutcome
    stratum: int | None = None


class _Stats(Protocol):
    offset: float
    stratum: int


Requester = Callable[[str, int, float], "_Stats"]


def _default_requester(host: str, version: int, timeout: float) -> _Stats:
    stats: _Stats = ntplib.NTPClient().request(
        host, version=version, timeout=timeout
    )
    return stats


class NTPClient:
    """Queries an NTP source and classifies the response."""

    def __init__(
        self,
        source: str,
        *,
        timeout: float = 5.0,
        version: int = 3,
        requester: Requester | None = None,
    ) -> None:
        self._source = source
        self._timeout = timeout
        self._version = version
        self._requester = requester or _default_requester

    @property
    def source(self) -> str:
        return self._source

    def measure(self) -> NTPMeasurement:
        """Query the source once and return a classified measurement.

        Raises :class:`NTPUnreachableError` on any network-level failure.
        """
        try:
            stats = self._requester(self._source, self._version, self._timeout)
        except (
            TimeoutError,
            socket.gaierror,
            ntplib.NTPException,
            OSError,
        ) as exc:
            raise NTPUnreachableError(
                f"NTP source {self._source!r} unreachable: {exc}"
            ) from exc

        offset = float(stats.offset)
        stratum = int(getattr(stats, "stratum", 0))
        measured_at = datetime.now(UTC)

        if (
            stratum >= _KISS_OF_DEATH_STRATUM
            or abs(offset) > _MAX_PLAUSIBLE_OFFSET_SECONDS
        ):
            return NTPMeasurement(
                self._source, offset, measured_at, "rejected_kod", stratum
            )
        return NTPMeasurement(self._source, offset, measured_at, "ok", stratum)


class NTPGate:
    """Startup gate: block until a clean, in-drift measurement (FR-022/024).

    Repeatedly measures until a non-rejected, reachable response arrives.
    If that response's offset exceeds ``max_drift_seconds`` the process
    must refuse to start; if no usable response arrives within
    ``timeout_seconds`` the process must also refuse to start. Either way
    a single ERROR line names the source and (when known) the offset.
    """

    def __init__(
        self,
        client: _Measurer,
        *,
        max_drift_seconds: float,
        timeout_seconds: float,
        poll_interval_seconds: float = 1.0,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._client = client
        self._max_drift = max_drift_seconds
        self._timeout = timeout_seconds
        self._poll = poll_interval_seconds
        self._sleep = sleep
        self._monotonic = monotonic

    def verify(self) -> NTPMeasurement:
        deadline = self._monotonic() + self._timeout
        while True:
            measurement: NTPMeasurement | None
            try:
                measurement = self._client.measure()
            except NTPUnreachableError:
                measurement = None

            if measurement is not None and measurement.outcome == "ok":
                if abs(measurement.offset_seconds) > self._max_drift:
                    logger.error(
                        "NTP startup gate FAILED: measured offset %.6fs "
                        "against source %s exceeds max drift %.3fs — "
                        "refusing to start (FR-022)",
                        measurement.offset_seconds,
                        self._client.source,
                        self._max_drift,
                    )
                    raise NTPStartupError(
                        f"clock offset {measurement.offset_seconds:.6f}s vs "
                        f"{self._client.source} exceeds max drift "
                        f"{self._max_drift}s"
                    )
                return measurement

            if self._monotonic() >= deadline:
                logger.error(
                    "NTP startup gate FAILED: no usable response from "
                    "source %s within %.0fs — refusing to start (FR-024)",
                    self._client.source,
                    self._timeout,
                )
                raise NTPStartupError(
                    f"NTP source {self._client.source} unreachable/invalid "
                    f"within {self._timeout}s"
                )
            self._sleep(self._poll)


@dataclass(frozen=True, slots=True)
class ClockSyncEvent:
    """A timestamped record of one NTP measurement (data-model.md)."""

    measured_at: datetime
    source: str
    offset_seconds: float
    outcome: ClockSyncOutcome
    correction_exit_code: int | None = None


class _DriftSink(Protocol):
    recent_clock_sync: ClockSyncEvent | None
    last_drift_warning: ClockSyncEvent | None


CorrectionRunner = Callable[[list[str]], int]


def _default_runner(argv: list[str]) -> int:
    return subprocess.run(argv, check=False).returncode


class DriftMonitor:
    """Recurring drift check + out-of-band clock correction (FR-023/024).

    Each cycle measures offset. Within threshold → ``ok``. Over threshold
    → invoke the configured privileged helper as ``[command, source]``;
    exit 0 → ``drift_corrected``, otherwise (non-zero, missing helper, or
    no command configured) → ``drift_uncorrected`` with a WARNING. An
    unreachable source or KoD response is a warning outcome but does not
    halt the process (running on the last-known-good clock, FR-024).
    """

    def __init__(
        self,
        client: _Measurer,
        *,
        max_drift_seconds: float,
        check_interval_seconds: float,
        correct_clock_command: str | None,
        runner: CorrectionRunner = _default_runner,
        sink: _DriftSink | None = None,
        on_event: Callable[[ClockSyncEvent], None] | None = None,
    ) -> None:
        self._client = client
        self._max_drift = max_drift_seconds
        self._interval = check_interval_seconds
        self._command = correct_clock_command
        self._runner = runner
        self._sink = sink
        self._on_event = on_event
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    # -- single cycle ----------------------------------------------------

    def check_once(self) -> ClockSyncEvent:
        source = self._client.source
        try:
            m = self._client.measure()
        except NTPUnreachableError:
            return self._record(
                ClockSyncEvent(
                    datetime.now(UTC), source, 0.0, "unreachable", None
                ),
                "NTP source %s unreachable mid-run — continuing on "
                "last-known-good clock (FR-024)",
                source,
            )

        if m.outcome == "rejected_kod":
            return self._record(
                ClockSyncEvent(
                    m.measured_at, m.source, m.offset_seconds, "rejected_kod"
                ),
                "NTP source %s returned an unusable (kiss-of-death) "
                "response — ignoring",
                source,
            )

        if abs(m.offset_seconds) <= self._max_drift:
            return self._record(
                ClockSyncEvent(
                    m.measured_at, m.source, m.offset_seconds, "ok"
                )
            )

        # Drift exceeds threshold — correction required (FR-023).
        if not self._command:
            return self._record(
                ClockSyncEvent(
                    m.measured_at,
                    m.source,
                    m.offset_seconds,
                    "drift_uncorrected",
                    None,
                ),
                "Clock drift %.6fs vs %s exceeds %.3fs but no correction "
                "command is configured (verify-only mode)",
                m.offset_seconds,
                source,
                self._max_drift,
            )

        try:
            code = self._runner([self._command, source])
        except FileNotFoundError:
            return self._record(
                ClockSyncEvent(
                    m.measured_at,
                    m.source,
                    m.offset_seconds,
                    "drift_uncorrected",
                    None,
                ),
                "Clock-correction helper %s not found — drift %.6fs vs %s "
                "left uncorrected",
                self._command,
                m.offset_seconds,
                source,
            )

        if code == 0:
            ev = ClockSyncEvent(
                m.measured_at,
                m.source,
                m.offset_seconds,
                "drift_corrected",
                0,
            )
            logger.info(
                "Clock drift %.6fs vs %s corrected via %s",
                m.offset_seconds,
                source,
                self._command,
            )
            return self._record(ev)

        return self._record(
            ClockSyncEvent(
                m.measured_at,
                m.source,
                m.offset_seconds,
                "drift_uncorrected",
                code,
            ),
            "Clock-correction helper %s exited %d — drift %.6fs vs %s "
            "left uncorrected",
            self._command,
            code,
            m.offset_seconds,
            source,
        )

    # -- background loop -------------------------------------------------

    def start(self) -> None:
        if self._thread is not None:
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._loop, name="ntp-drift-monitor", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5.0)
            self._thread = None

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.check_once()
            except Exception:  # noqa: BLE001 — never let the thread die
                logger.exception("DriftMonitor cycle raised — continuing")
            self._stop.wait(self._interval)

    # -- helpers ---------------------------------------------------------

    def _record(
        self, event: ClockSyncEvent, msg: str | None = None, *args: object
    ) -> ClockSyncEvent:
        if msg is not None:
            logger.warning(msg, *args)
        if self._sink is not None:
            self._sink.recent_clock_sync = event
            if event.outcome in _WARNING_OUTCOMES:
                self._sink.last_drift_warning = event
        if self._on_event is not None:
            self._on_event(event)
        return event

