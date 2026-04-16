"""
Entry point for pms-scanner.

Lifecycle
---------
1. Configure logging.
2. Register SIGTERM / SIGINT handlers for graceful shutdown.
3. Run startup() — create directories, recover in-progress files.
4. Capture asyncio event loop (for thread→async event queue bridging).
5. Start APScheduler — schedules execute_run every cron_interval_seconds.
6. Start uvicorn in the main thread (dashboard + SSE).

Graceful shutdown
-----------------
On SIGTERM or SIGINT the _shutdown() handler:
  - calls scheduler.shutdown(wait=True)  — waits for any in-flight batch thread
  - calls sys.exit(0)
"""

import asyncio
import logging
import signal
import sys

import uvicorn
from apscheduler.executors.pool import ThreadPoolExecutor  # type: ignore[import-untyped,unused-ignore]
from apscheduler.schedulers.background import BackgroundScheduler  # type: ignore[import-untyped,unused-ignore]
from .batch import execute_run, startup
from .config import settings
from .dashboard import app as dashboard_app
from .state import app_state

logging.basicConfig(
    level=settings.log_level.upper(),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

logger = logging.getLogger(__name__)

# Module-level scheduler reference — set before signal handlers fire.
scheduler: BackgroundScheduler | None = None


def _shutdown(signum: int, frame: object) -> None:  # noqa: ARG001
    """Handle SIGTERM / SIGINT: stop scheduler then exit."""
    sig_name = signal.Signals(signum).name
    logger.info("Graceful shutdown initiated (signal %s)", sig_name)
    if scheduler is not None and scheduler.running:
        scheduler.shutdown(wait=True)
    sys.exit(0)


signal.signal(signal.SIGTERM, _shutdown)
signal.signal(signal.SIGINT, _shutdown)


if __name__ == "__main__":
    logger.info(
        "pms-scanner starting — watch=%s  cron=%ds  dashboard=:%d",
        settings.watch_dir,
        settings.cron_interval_seconds,
        settings.dashboard_port,
    )

    # Step 3: startup (dirs + crash recovery)
    startup(app_state)

    # Step 4: capture the event loop for thread→async bridging
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    app_state.loop = loop

    # Step 5: APScheduler
    executors = {"default": ThreadPoolExecutor(max_workers=4)}
    scheduler = BackgroundScheduler(executors=executors)
    scheduler.add_job(
        execute_run,
        trigger="interval",
        seconds=settings.cron_interval_seconds,
        args=[app_state],
        id="batch_run",
        max_instances=1,
    )
    scheduler.start()
    logger.info("Scheduler started — interval=%ds", settings.cron_interval_seconds)

    # Step 6: uvicorn (blocks until process is killed)
    uvicorn_config = uvicorn.Config(
        dashboard_app,
        host="0.0.0.0",
        port=settings.dashboard_port,
        loop="none",  # we manage the event loop ourselves
        log_level=settings.log_level.lower(),
    )
    server = uvicorn.Server(uvicorn_config)
    loop.run_until_complete(server.serve())
