"""Unit tests for scanner/scheduler.py — T031 + T033 (004 US3).

build_jobs returns one CronTrigger spec per ENABLED env on this machine
with second=offset, minute='*', max_instances=1, coalesce=True,
misfire_grace_time=30 (FR-006/006b). Concurrency: two jobs firing in
the same second are serviced by two distinct worker threads (FR-006a).
"""
import os
import threading
import time
from pathlib import Path
from unittest.mock import patch

from config import load_settings
from scheduler import JobSpec, Scheduler, build_jobs


def _settings(tmp_path: Path, *, staging_enabled: bool = True):
    p = tmp_path / "p"
    s = tmp_path / "s"
    p.mkdir()
    s.mkdir()
    env = {
        "MACHINE_IDENTITY": "macmini",
        "NTP__STARTUP_REQUIRED": "false",
        "ENVIRONMENTS": "production,staging",
        "ENV_PRODUCTION__WATCH_DIR": str(p),
        "ENV_PRODUCTION__API_TOKEN": "pt",
        "ENV_PRODUCTION__SCHEDULE_OFFSET_SECONDS": "0",
        "ENV_STAGING__WATCH_DIR": str(s),
        "ENV_STAGING__API_TOKEN": "st",
        "ENV_STAGING__SCHEDULE_OFFSET_SECONDS": "15",
        "ENV_STAGING__ENABLED": "true" if staging_enabled else "false",
    }
    with patch.dict(os.environ, env, clear=True):
        return load_settings(dotenv=False)


def test_build_jobs_one_per_enabled_env(tmp_path: Path) -> None:
    jobs = build_jobs(_settings(tmp_path))
    by_env = {j.env_name: j for j in jobs}
    assert set(by_env) == {"production", "staging"}
    assert by_env["production"].trigger_kwargs == {"second": 0, "minute": "*"}
    assert by_env["staging"].trigger_kwargs == {"second": 15, "minute": "*"}
    for j in jobs:
        assert isinstance(j, JobSpec)
        assert j.max_instances == 1
        assert j.coalesce is True
        assert j.misfire_grace_time == 30
        assert j.job_id == f"macmini:{j.env_name}"


def test_build_jobs_excludes_disabled_env(tmp_path: Path) -> None:
    jobs = build_jobs(_settings(tmp_path, staging_enabled=False))
    assert [j.env_name for j in jobs] == ["production"]


def test_scheduler_registers_jobs_with_apscheduler(tmp_path: Path) -> None:
    s = _settings(tmp_path)
    sched = Scheduler(s, run_env=lambda _name: None)
    sched.register()
    try:
        ids = {j.id for j in sched._scheduler.get_jobs()}
        assert ids == {"macmini:production", "macmini:staging"}
        for job in sched._scheduler.get_jobs():
            assert job.max_instances == 1
            assert job.coalesce is True
    finally:
        sched.stop()


def test_concurrent_jobs_use_distinct_threads(tmp_path: Path) -> None:
    """Two envs firing within the same second run on distinct threads (T033)."""
    s = _settings(tmp_path)
    seen: dict[str, int] = {}
    barrier = threading.Barrier(2, timeout=5)

    def run_env(name: str) -> None:
        barrier.wait()  # both must be in-flight simultaneously
        seen[name] = threading.get_ident()

    sched = Scheduler(s, run_env=run_env)
    # Fire both envs ~now, one second apart at most.
    sched.register(immediate=True)
    sched.start()
    try:
        deadline = time.monotonic() + 5
        while len(seen) < 2 and time.monotonic() < deadline:
            time.sleep(0.05)
    finally:
        sched.stop()

    assert set(seen) == {"production", "staging"}
    assert seen["production"] != seen["staging"]  # distinct worker threads
