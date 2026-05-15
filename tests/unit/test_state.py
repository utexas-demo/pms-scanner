"""Unit tests for scanner/state.py — T006 (legacy) + T015/T017 (004)."""
import logging
import threading
from datetime import UTC, datetime

import pytest
from machine import MachineIdentity
from ntp import ClockSyncEvent
from state import (
    AppState,
    BatchRunState,
    ErrorRecord,
    FileResult,
    PageResult,
    PerEnvRunState,
    RunRecord,
    make_logger,
)


def test_app_state_initial_values():
    """AppState initialises with current_run=None and last_run=None."""
    s = AppState()
    assert s.current_run is None
    assert s.last_run is None


def test_app_state_has_lock():
    """AppState._lock is a threading.Lock."""
    s = AppState()
    assert isinstance(s._lock, type(threading.Lock()))


def test_page_result_fields():
    """PageResult stores all required fields."""
    p = PageResult(page_num=1, total_pages=5, rotation_applied=90, upload_success=True)
    assert p.page_num == 1
    assert p.total_pages == 5
    assert p.rotation_applied == 90
    assert p.orientation_uncertain is False
    assert p.upload_success is True
    assert p.error is None


def test_file_result_defaults():
    """FileResult starts with status=pending and empty pages list."""
    f = FileResult(filename="test.pdf", total_pages=3)
    assert f.status == "pending"
    assert f.pages == []
    assert isinstance(f.started_at, datetime)
    assert f.completed_at is None


def test_batch_run_state_has_run_id():
    """RunRecord auto-generates a run_id UUID string."""
    r = RunRecord()
    assert isinstance(r.run_id, str)
    assert len(r.run_id) == 36  # UUID4 format


def test_batch_run_state_defaults():
    """RunRecord starts with status=running and empty lists."""
    r = RunRecord()
    assert r.status == "running"
    assert r.files == []
    assert r.recovered_files == []


def test_app_state_lock_prevents_concurrent_mutation():
    """Acquiring _lock blocks concurrent writes."""
    s = AppState()
    results: list[int] = []

    def writer(val: int) -> None:
        with s._lock:
            results.append(val)

    threads = [threading.Thread(target=writer, args=(i,)) for i in range(50)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(results) == 50
    assert sorted(results) == list(range(50))


def test_to_status_dict_structure():
    """to_status_dict returns dict with current_run and last_run keys."""
    s = AppState()
    d = s.to_status_dict()
    assert "current_run" in d
    assert "last_run" in d
    assert d["current_run"] is None
    assert d["last_run"] is None


def test_to_status_dict_with_run():
    """to_status_dict serialises a RunRecord correctly."""
    s = AppState()
    run = RunRecord()
    with s._lock:
        s.current_run = run
    d = s.to_status_dict()
    assert d["current_run"] is not None
    assert d["current_run"]["run_id"] == run.run_id
    assert d["current_run"]["status"] == "running"
    assert isinstance(d["current_run"]["files"], list)


# ---------------------------------------------------------------------------
# T015 — per-(machine, env) BatchRunState container
# ---------------------------------------------------------------------------


def _state() -> BatchRunState:
    return BatchRunState(MachineIdentity("macmini"), ["production", "staging"])


def test_batch_run_state_keyed_by_env_name() -> None:
    s = _state()
    assert set(s.per_env) == {"production", "staging"}
    prod = s.env("production")
    assert isinstance(prod, PerEnvRunState)
    assert prod.environment == "production"
    assert prod.machine == "macmini"


def test_unknown_env_raises_key_error() -> None:
    with pytest.raises(KeyError):
        _state().env("qa")


def test_per_env_counters_move_independently() -> None:
    s = _state()
    s.add_pages_uploaded("production", 3)
    s.add_files_processed("production", 1)
    assert s.env("production").pages_uploaded == 3
    assert s.env("production").files_processed == 1
    assert s.env("staging").pages_uploaded == 0
    assert s.env("staging").files_processed == 0


def test_add_error_is_scoped_per_env() -> None:
    s = _state()
    s.add_error(
        "staging",
        ErrorRecord(filename="x.pdf", message="boom", page_num=2),
    )
    assert len(s.env("staging").errors) == 1
    assert s.env("staging").errors[0].filename == "x.pdf"
    assert s.env("production").errors == []


def test_clock_sync_event_storage() -> None:
    s = _state()
    ok = ClockSyncEvent(datetime.now(UTC), "pool.ntp.org", 0.01, "ok")
    s.record_clock_sync(ok)
    assert s.recent_clock_sync is ok
    assert s.last_drift_warning is None

    bad = ClockSyncEvent(
        datetime.now(UTC), "pool.ntp.org", 5.0, "drift_uncorrected", 1
    )
    s.record_clock_sync(bad)
    assert s.recent_clock_sync is bad
    assert s.last_drift_warning is bad


def test_concurrent_mutation_under_rlock_loses_nothing() -> None:
    s = _state()
    threads_n, per_thread = 16, 500

    def worker() -> None:
        for _ in range(per_thread):
            s.add_pages_uploaded("production", 1)

    threads = [threading.Thread(target=worker) for _ in range(threads_n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert s.env("production").pages_uploaded == threads_n * per_thread


def test_state_satisfies_drift_sink_protocol() -> None:
    # DriftMonitor sets these attributes directly; they must exist + be writable.
    s = _state()
    ev = ClockSyncEvent(datetime.now(UTC), "src", 0.0, "ok")
    s.recent_clock_sync = ev
    s.last_drift_warning = ev
    assert s.recent_clock_sync is ev


# ---------------------------------------------------------------------------
# T017 — env+machine logger adapter with secret redaction
# ---------------------------------------------------------------------------


def test_logger_tags_env_and_machine(caplog: pytest.LogCaptureFixture) -> None:
    log = make_logger("scanner.test", machine="macmini", env="production")
    with caplog.at_level(logging.INFO, logger="scanner.test"):
        log.info("hello")
    msg = caplog.records[-1].getMessage()
    assert "machine=macmini" in msg
    assert "env=production" in msg


def test_logger_redacts_registered_secret(
    caplog: pytest.LogCaptureFixture,
) -> None:
    log = make_logger(
        "scanner.test2",
        machine="nuc",
        env="staging",
        secrets=["pms_supersecret_token"],
    )
    with caplog.at_level(logging.INFO, logger="scanner.test2"):
        log.info("auth header bearer pms_supersecret_token done")
    msg = caplog.records[-1].getMessage()
    assert "pms_supersecret_token" not in msg
    assert "***" in msg
