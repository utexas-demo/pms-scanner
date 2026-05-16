"""Integration test for the NTP startup gate — T011 (004 foundational).

The gate must block scheduler registration until a clean response arrives,
and MUST refuse to start (single ERROR log naming source + measured offset)
when the offset exceeds max_drift_seconds (FR-022) or the source never
yields a usable response within the timeout (FR-024).
"""
import itertools
import logging

import pytest
from ntp import (
    NTPGate,
    NTPMeasurement,
    NTPStartupError,
    NTPUnreachableError,
)


def _ok(offset: float) -> NTPMeasurement:
    from datetime import UTC, datetime

    return NTPMeasurement(
        "pool.ntp.org", offset, datetime.now(UTC), "ok", stratum=2
    )


def _kod() -> NTPMeasurement:
    from datetime import UTC, datetime

    return NTPMeasurement(
        "pool.ntp.org", 0.01, datetime.now(UTC), "rejected_kod", stratum=16
    )


class _ScriptedClient:
    """Yields a scripted sequence; an item may be an exception to raise."""

    source = "pool.ntp.org"

    def __init__(self, script: list[object]) -> None:
        self._it = iter(script)
        self.calls = 0

    def measure(self) -> NTPMeasurement:
        self.calls += 1
        item = next(self._it)
        if isinstance(item, Exception):
            raise item
        assert isinstance(item, NTPMeasurement)
        return item


def _gate(client: object, **kw: object) -> NTPGate:
    defaults: dict[str, object] = {
        "max_drift_seconds": 1.0,
        "timeout_seconds": 30.0,
        "poll_interval_seconds": 0.0,
        "sleep": lambda _s: None,
    }
    defaults.update(kw)
    return NTPGate(client, **defaults)  # type: ignore[arg-type]


def test_first_clean_within_drift_passes_immediately() -> None:
    client = _ScriptedClient([_ok(0.5)])
    m = _gate(client).verify()
    assert m.outcome == "ok"
    assert client.calls == 1


def test_blocks_until_clean_response(caplog: pytest.LogCaptureFixture) -> None:
    client = _ScriptedClient(
        [NTPUnreachableError("net down"), _kod(), _ok(0.2)]
    )
    m = _gate(client).verify()
    assert m.offset_seconds == pytest.approx(0.2)
    assert client.calls == 3  # retried past the unreachable + KoD


def test_drift_exceeds_max_refuses_to_start(
    caplog: pytest.LogCaptureFixture,
) -> None:
    client = _ScriptedClient([_ok(2.0)])
    with caplog.at_level(logging.ERROR):
        with pytest.raises(NTPStartupError):
            _gate(client, max_drift_seconds=1.0).verify()
    errors = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert len(errors) == 1
    msg = errors[0].getMessage()
    assert "pool.ntp.org" in msg and "2.0" in msg


def test_never_clean_within_timeout_refuses_to_start(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # monotonic advances 10s per call; timeout 30s → ~3 attempts then abort.
    ticks = itertools.count(0, 10)
    client = _ScriptedClient([NTPUnreachableError("down")] * 50)
    with caplog.at_level(logging.ERROR):
        with pytest.raises(NTPStartupError):
            _gate(
                client,
                timeout_seconds=30.0,
                monotonic=lambda: float(next(ticks)),
            ).verify()
    errors = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert len(errors) == 1
    assert "pool.ntp.org" in errors[0].getMessage()
