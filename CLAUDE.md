# pms-scanner Development Guidelines

Auto-generated from all feature plans. Last updated: 2026-04-14

## Active Technologies

- Python 3.12 (003-we-watch-all)
- PyMuPDF (fitz), Pillow, pytesseract — PDF rendering + OSD orientation
- FastAPI, uvicorn — dashboard + SSE
- APScheduler — cron scheduling
- requests — backend uploads

## Project Structure

```text
scanner/        # main package (batch, dashboard, pdf_processor, uploader, state, config)
tests/unit/
tests/integration/
tests/contract/
launchd/        # io.mpsinc.pms-scanner.plist (macOS LaunchAgent)
docs/           # launchd-setup.md
```

## Commands

```sh
pytest --ignore=tests/contract --cov=scanner
ruff check .
mypy --strict scanner/
python -m scanner   # run locally
```

## Code Style

Python 3.12: Follow standard conventions; ruff + mypy --strict enforced.

## Deployment

macOS launchd LaunchAgent (`launchd/io.mpsinc.pms-scanner.plist`). See
`docs/launchd-setup.md`. Dashboard on `http://localhost:8080` by default.

## Recent Changes

- 003-we-watch-all: macOS-native PDF batch processor with cron scheduling and
  live dashboard; replaced watchdog watcher with APScheduler + FastAPI SSE.

<!-- MANUAL ADDITIONS START -->
<!-- MANUAL ADDITIONS END -->
