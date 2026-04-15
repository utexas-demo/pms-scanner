# pms-scanner

macOS service that watches a folder for PDF files, extracts and orients every page, and uploads each page to the pms-backend.

## What it does

- **Watches** `/Volumes/aria/ARIAscans` (configurable) every 60 seconds for new PDF files
- **Processes** each PDF: counts pages, detects rotation via PyMuPDF metadata + Tesseract OSD fallback, corrects orientation
- **Uploads** every page individually to `POST {BACKEND_BASE_URL}/api/scanned-images/upload`
- **Reports** live progress in a browser dashboard (`http://localhost:8080`)
- **Runs** as a macOS launchd LaunchAgent — starts at login, survives reboots, waits for the ARIA SMB share before starting

## Quick Start (macOS)

### Prerequisites

```bash
brew install tesseract
python3.12 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

### Configure

```bash
cp .env.example .env
# Edit .env — set BACKEND_BASE_URL, API_TOKEN, WATCH_DIR
```

### Run manually

```bash
.venv/bin/python -m scanner
```

Open the dashboard: http://localhost:8080

### Install as a macOS service

See [docs/launchd-setup.md](docs/launchd-setup.md) for full instructions.

```bash
# Quick install
sed -i '' "s/YOUR_USERNAME/$(whoami)/g" launchd/io.mpsinc.pms-scanner.plist
cp launchd/io.mpsinc.pms-scanner.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/io.mpsinc.pms-scanner.plist
```

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `WATCH_DIR` | `/Volumes/aria/ARIAscans` | Folder to scan for PDF files |
| `CRON_INTERVAL_SECONDS` | `60` | How often to check the folder (seconds) |
| `FILE_SETTLE_SECONDS` | `10.0` | Minimum age (seconds) before a file is processed |
| `DASHBOARD_PORT` | `8080` | Web dashboard port |
| `BACKEND_BASE_URL` | *(required)* | Base URL of pms-backend |
| `API_TOKEN` | *(required)* | JWT Bearer token for the backend |
| `UPLOAD_TIMEOUT_SECONDS` | `30` | HTTP timeout for upload requests |
| `UPLOAD_MAX_RETRIES` | `3` | Max upload attempts per page (retries on 5xx) |
| `UPLOAD_RETRY_MAX_WAIT_SECONDS` | `10` | Max wait between retries (exponential back-off cap) |
| `LOG_LEVEL` | `INFO` | Logging verbosity: `DEBUG`, `INFO`, `WARNING`, `ERROR` |

## File Lifecycle

```
/Volumes/aria/ARIAscans/
├── *.pdf               ← scanner drops files here
├── in-progress/
│   └── *.pdf           ← atomically claimed during processing
│                       ← crash recovery: returned to root on next run start
└── processed/
    └── *.pdf           ← successfully processed files
```

If processing fails (e.g. upload error), the file is returned to the root folder for retry on the next cron tick.  
If the process crashes mid-run, files in `in-progress/` are automatically returned to the root on the next startup.

## Dashboard

Navigate to **http://localhost:8080** to see:

- Current run status and active filename
- Per-page progress counter (e.g. `7 / 33`)
- Last-run summary
- A **Run Now** button to trigger an immediate scan

The dashboard uses Server-Sent Events (SSE) for real-time push updates — no polling required.

## Development

```bash
# Install dev dependencies
.venv/bin/pip install -r requirements-dev.txt

# Run tests
.venv/bin/python -m pytest

# Lint + type-check
.venv/bin/ruff check scanner/ tests/
.venv/bin/mypy --strict scanner/
```

## Architecture

| Module | Role |
|--------|------|
| `scanner/config.py` | Pydantic settings loaded from `.env` |
| `scanner/state.py` | In-memory state dataclasses; `AppState` singleton with `threading.Lock` |
| `scanner/pdf_processor.py` | PyMuPDF page extraction + two-tier orientation detection |
| `scanner/uploader.py` | HTTP upload with exponential back-off retry |
| `scanner/batch.py` | Main batch runner: crash recovery → settle filter → atomic claim → process → upload → disposition |
| `scanner/dashboard.py` | FastAPI web app: status JSON, SSE events stream, manual trigger |
| `scanner/__main__.py` | Entry point: APScheduler + uvicorn wiring, SIGTERM/SIGINT handler |
