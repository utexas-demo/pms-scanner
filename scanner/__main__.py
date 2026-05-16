"""Entry point for pms-scanner (004 — multi-env, fleet-aware).

Startup order (data-model.md §"Startup validation order"):

1-3,7. ``load_settings()`` validates machine identity, required fields,
        distinct watch dirs (FR-009), distinct offsets (FR-006c), tokens.
4-5.   NTP startup gate measures offset and refuses to start on excess
        drift / unreachable source (FR-022/024).
6.     Per-machine ``in-progress/<machine>/`` (mode 0700 on POSIX) and
        ``processed/`` directories are created for every enabled env.

Then: assemble :class:`BatchRunState`, start the dashboard, register the
scheduler (placeholder until T032/T035 wires per-env jobs), start the
:class:`DriftMonitor`, install SIGTERM/SIGINT drain handlers, run uvicorn.
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import sys
from dataclasses import dataclass

import uvicorn

from .config import AppSettings, ConfigError, load_settings
from .dashboard import app as dashboard_app
from .dashboard import configure as _configure_dashboard
from .ntp import (
    ClockSyncEvent,
    DriftMonitor,
    NTPClient,
    NTPGate,
    NTPStartupError,
)
from .scheduler import Scheduler
from .state import BatchRunState

logger = logging.getLogger("scanner.main")

# Module-level handles — set by main(), read by the signal handler.
scheduler: Scheduler | None = None
drift_monitor: DriftMonitor | None = None


@dataclass(slots=True)
class Runtime:
    """Everything main() needs after startup validation passes."""

    settings: AppSettings
    state: BatchRunState
    drift_monitor: DriftMonitor


def _create_dirs(settings: AppSettings) -> None:
    for env in settings.enabled_environments:
        in_self = env.in_progress_dir(settings.machine)
        env.in_progress_root.mkdir(parents=True, exist_ok=True)
        in_self.mkdir(parents=True, exist_ok=True)
        env.processed_dir.mkdir(parents=True, exist_ok=True)
        if os.name == "posix":
            os.chmod(in_self, 0o700)


def build_runtime(
    settings: AppSettings,
    *,
    ntp_client: NTPClient | None = None,
) -> Runtime:
    """Run the NTP gate, create dirs, and assemble runtime state.

    Raises :class:`NTPStartupError` if the startup gate fails — the caller
    must treat that as a refuse-to-start condition (exit 1).
    """
    client = ntp_client or NTPClient(
        settings.ntp.source, timeout=float(settings.ntp.startup_timeout_seconds)
    )

    state = BatchRunState(
        settings.machine, [e.name for e in settings.environments]
    )

    if settings.ntp.startup_required:
        gate = NTPGate(
            client,
            max_drift_seconds=settings.ntp.max_drift_seconds,
            timeout_seconds=float(settings.ntp.startup_timeout_seconds),
        )
        measurement = gate.verify()
        state.record_clock_sync(
            ClockSyncEvent(
                measurement.measured_at,
                measurement.source,
                measurement.offset_seconds,
                "ok",
            )
        )
        logger.info(
            "NTP startup gate passed: offset %.6fs vs %s",
            measurement.offset_seconds,
            measurement.source,
        )
    else:
        logger.warning(
            "NTP startup gate DISABLED (NTP__STARTUP_REQUIRED=false) — "
            "for local development only; the fleet stride is unverified"
        )

    _create_dirs(settings)

    monitor = DriftMonitor(
        client,
        max_drift_seconds=settings.ntp.max_drift_seconds,
        check_interval_seconds=float(settings.ntp.check_interval_seconds),
        correct_clock_command=settings.ntp.correct_clock_command,
        sink=state,
    )
    return Runtime(settings=settings, state=state, drift_monitor=monitor)


def configure_services(runtime: Runtime) -> Scheduler:
    """Recover stranded files, wire the dashboard, register per-env jobs.

    Crash recovery (FR-008) runs for every enabled env BEFORE any
    scheduler job can fire, and only touches this machine's own
    in-progress/<machine>/ subfolder.
    """
    from .batch import BatchRunner

    for env in runtime.settings.enabled_environments:
        BatchRunner(
            env, runtime.settings.machine, runtime.state
        ).recover_stranded()

    _configure_dashboard(runtime.settings, runtime.state)
    sched = Scheduler(runtime.settings, runtime.state)
    sched.register()
    logger.info(
        "Registered %d per-env scheduler job(s) for machine=%s",
        len(runtime.settings.enabled_environments),
        runtime.settings.machine.name,
    )
    return sched


def _shutdown(signum: int, frame: object) -> None:  # noqa: ARG001
    """SIGTERM/SIGINT: drain scheduler + drift monitor, then exit."""
    sig_name = signal.Signals(signum).name
    logger.info("Graceful shutdown initiated (signal %s)", sig_name)
    if scheduler is not None and scheduler.running:
        scheduler.shutdown(wait=True)
    if drift_monitor is not None:
        drift_monitor.stop()
    sys.exit(0)


def main() -> None:
    global scheduler, drift_monitor

    try:
        settings = load_settings()
    except ConfigError as exc:
        logging.basicConfig(level="ERROR")
        logger.error("Configuration error — refusing to start: %s", exc)
        sys.exit(1)

    logging.basicConfig(
        level=settings.log_level.upper(),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    logger.info(
        "pms-scanner starting — machine=%s envs=%s dashboard=:%d",
        settings.machine.name,
        [e.name for e in settings.enabled_environments],
        settings.dashboard_port,
    )

    try:
        runtime = build_runtime(settings)
    except NTPStartupError as exc:
        logger.error("NTP startup gate failed — refusing to start: %s", exc)
        sys.exit(1)

    drift_monitor = runtime.drift_monitor

    # Event loop for the thread→async SSE bridge (dashboard).
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    scheduler = configure_services(runtime)
    scheduler.start()
    logger.info("Scheduler started — per-env jobs registered")

    drift_monitor.start()
    logger.info(
        "DriftMonitor started — interval=%ds",
        settings.ntp.check_interval_seconds,
    )

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    uvicorn_config = uvicorn.Config(
        dashboard_app,
        host="0.0.0.0",
        port=settings.dashboard_port,
        loop="none",
        log_level=settings.log_level.lower(),
    )
    server = uvicorn.Server(uvicorn_config)
    loop.run_until_complete(server.serve())


if __name__ == "__main__":
    main()
