# pms-scanner Development Guidelines

Auto-generated from all feature plans. Last updated: 2026-04-08

## Active Technologies

- **Python 3.12** — runtime
- **watchdog ≥4.0** — filesystem monitoring
- **requests** — HTTP upload client
- **tenacity ≥8.0** — retry logic (stop_after_attempt(3), wait_exponential)
- **pydantic-settings** — environment variable configuration
- **fastapi ≥0.100.0** — dashboard HTTP server (Feature 002)
- **uvicorn[standard] ≥0.24.0** — ASGI server run in background thread (Feature 002)
- **sse-starlette ≥2.1.0** — Server-Sent Events for real-time dashboard (Feature 002)

## Project Structure

```text
scanner/
├── __init__.py
├── __main__.py       # entry point: starts watcher + uvicorn API thread
├── config.py         # Settings (pydantic-settings): all env vars
├── watcher.py        # watchdog handler, upload_image(), process_file(), build_observer()
├── store.py          # StatusStore singleton, FileRecord, Status enum (Feature 002)
└── api.py            # FastAPI app, SSE endpoint, dashboard HTML (Feature 002)

tests/
├── conftest.py       # env var defaults for test isolation
├── unit/             # pure logic: config, watcher functions, store, api routes
├── integration/      # watcher lifecycle, HTTP upload, SSE event flow
└── contract/         # backend upload contract

specs/
├── 001-folder-monitor-upload/   # Feature 001 spec, plan, tasks (complete)
└── 002-upload-progress-ui/      # Feature 002 spec, plan, tasks (in progress)
```

## Commands

```bash
# Install
pip install -r requirements.txt -r requirements-dev.txt

# Test
pytest
pytest --cov=scanner --cov-report=term-missing

# Lint + format
ruff check .
ruff format --check .

# Type check
mypy --strict scanner/

# Run service
python -m scanner
```

## Code Style

- All code passes `ruff` (line-length=100, target-version=py312) and `mypy --strict`.
- Test coverage ≥ 90% required on all non-trivial modules.
- TDD mandatory: failing test committed before implementation (Constitution Principle II).
- Use `# pragma: no cover` only for entry-point functions not feasibly unit-tested (e.g. `run()`).
- Module-level singletons (`settings`, `status_store`) use `# type: ignore[call-arg]` where needed.

## Environment Variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `BACKEND_UPLOAD_URL` | **Yes** | — | Backend upload endpoint |
| `API_TOKEN` | **Yes** | — | Bearer token |
| `WATCH_DIR` | No | `/data/incoming` | Folder to monitor |
| `WATCH_RECURSIVE` | No | `true` | Monitor subdirectories |
| `FILE_SETTLE_SECONDS` | No | `0.5` | Settle delay before upload |
| `UPLOAD_TIMEOUT_SECONDS` | No | `30` | HTTP timeout per attempt |
| `LOG_LEVEL` | No | `INFO` | Log verbosity |
| `DASHBOARD_PORT` | No | `8080` | Dashboard HTTP port (Feature 002) |

<!-- MANUAL ADDITIONS START -->
<!-- MANUAL ADDITIONS END -->
