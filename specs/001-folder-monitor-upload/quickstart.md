# Developer Quickstart: Folder Monitor and File Upload

**Branch**: `001-folder-monitor-upload` | **Date**: 2026-04-08

## Prerequisites

- Docker Desktop (Windows 10/11 x64) — recommended
- Python 3.12+ (for running tests locally without Docker)
- `pip` and `venv`

---

## Run with Docker (recommended)

```bash
# 1. Copy and configure environment
cp .env.example .env
# Edit .env: set BACKEND_UPLOAD_URL and API_TOKEN

# 2. Create the incoming folder
mkdir incoming

# 3. Start the service
docker compose up --build

# 4. Drop a test image into the watch folder
copy test.jpg incoming\

# The service logs should show detection and upload within ~1 second.
```

---

## Run locally (Python)

```bash
# 1. Create and activate virtual environment
python -m venv .venv
.venv\Scripts\activate      # Windows
# source .venv/bin/activate  # Linux/Mac

# 2. Install dependencies
pip install -r requirements.txt
pip install -r requirements-dev.txt  # dev tools: pytest, ruff, mypy, tenacity

# 3. Configure environment
cp .env.example .env
# Edit .env: set WATCH_DIR, BACKEND_UPLOAD_URL, API_TOKEN

# 4. Run the service
python -m scanner
```

---

## Run Tests

```bash
# All tests
pytest

# Unit tests only
pytest tests/unit/

# Integration tests (requires mock server)
pytest tests/integration/

# Contract tests (validates upload request shape)
pytest tests/contract/

# With coverage report
pytest --cov=scanner --cov-report=term-missing
```

---

## Quality Gates

```bash
# Linting + formatting
ruff check .
ruff format --check .

# Type checking
mypy --strict scanner/

# All gates together (run before every commit)
ruff check . && ruff format --check . && mypy --strict scanner/ && pytest --cov=scanner
```

---

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `WATCH_DIR` | No | `/data/incoming` | Absolute path to the folder to monitor |
| `WATCH_RECURSIVE` | No | `true` | Monitor subdirectories |
| `FILE_SETTLE_SECONDS` | No | `0.5` | Delay (seconds) after detection before upload |
| `BACKEND_UPLOAD_URL` | **Yes** | — | Full URL of the backend upload endpoint |
| `API_TOKEN` | **Yes** | — | Bearer token for backend authentication |
| `UPLOAD_TIMEOUT_SECONDS` | No | `30` | HTTP request timeout per attempt |
| `LOG_LEVEL` | No | `INFO` | Logging verbosity: DEBUG \| INFO \| WARNING \| ERROR |

---

## Architecture (one-paragraph summary)

The service runs a single `watchdog.Observer` thread that watches `WATCH_DIR`. When a new image file is detected (`on_created` / `on_moved`), its path is placed on a `queue.Queue`. A dedicated worker thread consumes the queue: it waits `FILE_SETTLE_SECONDS`, then attempts to POST the file to `BACKEND_UPLOAD_URL` with Bearer authentication. Failed uploads are retried up to 3 times with exponential back-off (tenacity). All outcomes are logged. The service handles `SIGTERM` and `KeyboardInterrupt` gracefully, stopping the observer and draining the queue before exit.
