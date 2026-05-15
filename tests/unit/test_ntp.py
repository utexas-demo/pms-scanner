"""Unit tests for scanner/ntp.py — T009 (NTPClient) + T013 (DriftMonitor).

T013 cases are appended in a later commit; this file starts with the
NTPClient measurement contract (T009): clean offset, kiss-of-death
(stratum 16) rejection, implausible (>1 day) offset rejection, and
network error → NTPUnreachableError.
"""
import logging
import socket
from types import SimpleNamespace

import ntplib
import pytest
from ntp import (
    ClockSyncEvent,
    DriftMonitor,
    NTPClient,
    NTPMeasurement,
    NTPUnreachableError,
)


class _FakeStats:
    def __init__(self, offset: float, stratum: int = 2) -> None:
        self.offset = offset
        self.stratum = stratum


def _client(requester) -> NTPClient:
    return NTPClient("pool.ntp.org", timeout=1.0, requester=requester)


def test_clean_offset_measurement_is_ok() -> None:
    c = _client(lambda host, version, timeout: _FakeStats(0.043, stratum=2))
    m = c.measure()
    assert m.outcome == "ok"
    assert m.offset_seconds == pytest.approx(0.043)
    assert m.source == "pool.ntp.org"
    assert m.stratum == 2


def test_kiss_of_death_stratum_16_rejected() -> None:
    c = _client(lambda host, version, timeout: _FakeStats(0.01, stratum=16))
    m = c.measure()
    assert m.outcome == "rejected_kod"


def test_implausible_offset_over_one_day_rejected() -> None:
    c = _client(lambda host, version, timeout: _FakeStats(90_000.0, stratum=2))
    m = c.measure()
    assert m.outcome == "rejected_kod"


@pytest.mark.parametrize(
    "exc",
    [
        TimeoutError("timed out"),
        socket.gaierror("name resolution failed"),
        ntplib.NTPException("no response"),
        OSError("network unreachable"),
    ],
)
def test_network_error_raises_unreachable(exc: Exception) -> None:
    def boom(host: str, version: int, timeout: float):
        raise exc

    with pytest.raises(NTPUnreachableError):
        _client(boom).measure()


def test_measured_at_is_timezone_aware_utc() -> None:
    c = _client(lambda host, version, timeout: _FakeStats(0.0))
    m = c.measure()
    assert m.measured_at.tzinfo is not None
    assert m.measured_at.utcoffset() is not None
    assert m.measured_at.utcoffset().total_seconds() == 0


# ---------------------------------------------------------------------------
# T013 — DriftMonitor recurring check + helper invocation
# ---------------------------------------------------------------------------


class _OneShotClient:
    source = "pool.ntp.org"

    def __init__(self, result: object) -> None:
        self._result = result

    def measure(self) -> NTPMeasurement:
        if isinstance(self._result, Exception):
            raise self._result
        assert isinstance(self._result, NTPMeasurement)
        return self._result


def _meas(offset: float, outcome: str = "ok", stratum: int = 2) -> NTPMeasurement:
    from datetime import UTC, datetime

    return NTPMeasurement(
        "pool.ntp.org", offset, datetime.now(UTC), outcome, stratum  # type: ignore[arg-type]
    )


def _sink() -> SimpleNamespace:
    return SimpleNamespace(recent_clock_sync=None, last_drift_warning=None)


def _monitor(client: object, runner, sink: SimpleNamespace, cmd: str | None):
    return DriftMonitor(
        client,  # type: ignore[arg-type]
        max_drift_seconds=1.0,
        check_interval_seconds=3600,
        correct_clock_command=cmd,
        runner=runner,
        sink=sink,
    )


def test_within_threshold_is_ok_no_correction() -> None:
    calls: list[list[str]] = []
    sink = _sink()
    ev = _monitor(
        _OneShotClient(_meas(0.2)), lambda a: calls.append(a) or 0, sink, "/bin/fix"
    ).check_once()
    assert ev.outcome == "ok"
    assert calls == []  # helper never invoked
    assert sink.recent_clock_sync is ev
    assert sink.last_drift_warning is None


def test_over_threshold_invokes_helper_with_configured_command() -> None:
    calls: list[list[str]] = []
    sink = _sink()
    ev = _monitor(
        _OneShotClient(_meas(5.0)),
        lambda argv: calls.append(argv) or 0,
        sink,
        "/usr/local/libexec/pms-scanner-correct-clock",
    ).check_once()
    assert ev.outcome == "drift_corrected"
    assert ev.correction_exit_code == 0
    assert calls == [["/usr/local/libexec/pms-scanner-correct-clock", "pool.ntp.org"]]
    assert sink.recent_clock_sync is ev


def test_helper_nonzero_exit_warns_and_sets_last_drift_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    sink = _sink()
    with caplog.at_level(logging.WARNING):
        ev = _monitor(
            _OneShotClient(_meas(5.0)), lambda argv: 3, sink, "/bin/fix"
        ).check_once()
    assert ev.outcome == "drift_uncorrected"
    assert ev.correction_exit_code == 3
    assert sink.last_drift_warning is ev
    assert any(r.levelno == logging.WARNING for r in caplog.records)


def test_helper_missing_takes_same_warning_path(
    caplog: pytest.LogCaptureFixture,
) -> None:
    def missing(argv: list[str]) -> int:
        raise FileNotFoundError(argv[0])

    sink = _sink()
    with caplog.at_level(logging.WARNING):
        ev = _monitor(
            _OneShotClient(_meas(5.0)), missing, sink, "/nope/missing"
        ).check_once()
    assert ev.outcome == "drift_uncorrected"
    assert sink.last_drift_warning is ev
    assert any(r.levelno == logging.WARNING for r in caplog.records)


def test_no_command_configured_is_drift_uncorrected(
    caplog: pytest.LogCaptureFixture,
) -> None:
    sink = _sink()
    with caplog.at_level(logging.WARNING):
        ev = _monitor(
            _OneShotClient(_meas(5.0)), lambda argv: 0, sink, None
        ).check_once()
    assert ev.outcome == "drift_uncorrected"
    assert ev.correction_exit_code is None
    assert sink.last_drift_warning is ev


def test_unreachable_mid_run_warns_and_continues(
    caplog: pytest.LogCaptureFixture,
) -> None:
    sink = _sink()
    with caplog.at_level(logging.WARNING):
        ev = _monitor(
            _OneShotClient(NTPUnreachableError("down")),
            lambda argv: 0,
            sink,
            "/bin/fix",
        ).check_once()
    assert ev.outcome == "unreachable"
    assert sink.last_drift_warning is ev
    assert any(r.levelno == logging.WARNING for r in caplog.records)


def test_rejected_kod_is_warning_outcome() -> None:
    sink = _sink()
    ev = _monitor(
        _OneShotClient(_meas(0.01, outcome="rejected_kod", stratum=16)),
        lambda argv: 0,
        sink,
        "/bin/fix",
    ).check_once()
    assert ev.outcome == "rejected_kod"
    assert sink.last_drift_warning is ev


def test_clock_sync_event_shape() -> None:
    ev = ClockSyncEvent(
        measured_at=_meas(0.0).measured_at,
        source="pool.ntp.org",
        offset_seconds=0.0,
        outcome="ok",
        correction_exit_code=None,
    )
    assert ev.outcome == "ok"
    assert ev.correction_exit_code is None
