"""Unit tests for scanner/ntp.py — T009 (NTPClient) + T013 (DriftMonitor).

T013 cases are appended in a later commit; this file starts with the
NTPClient measurement contract (T009): clean offset, kiss-of-death
(stratum 16) rejection, implausible (>1 day) offset rejection, and
network error → NTPUnreachableError.
"""
import socket

import ntplib
import pytest
from ntp import NTPClient, NTPUnreachableError


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
