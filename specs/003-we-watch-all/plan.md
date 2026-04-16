# Implementation Plan: PDF Scan Batch Processing with Cron Scheduling and Progress Dashboard

**Branch**: `003-we-watch-all` | **Date**: 2026-04-14 | **Spec**: [spec.md](./spec.md)  
**Input**: Feature specification from `specs/003-we-watch-all/spec.md`

## Summary

Replace the existing real-time file watcher with a cron-driven batch processor that: scans `ARIAscans/` every minute for new PDFs, atomically claims each file, extracts and orientation-corrects every page via PyMuPDF, uploads each page individually to the existing backend endpoint, and streams live progress to a lightweight web dashboard (FastAPI + SSE) accessible from any device on the local network. The entire stack runs as a single persistent macOS launchd daemon — no Docker required.

## Technical Context

**Language/Version**: Python 3.12  
**Primary Dependencies (existing)**: `pydantic-settings`, `python-dotenv`, `requests`, `watchdog` (to be removed)  
**Primary Dependencies (new)**: `pymupdf` (PDF render + rotation), `Pillow` (image handling), `pytesseract` (OSD orientation fallback — requires `brew install tesseract`), `fastapi`, `uvicorn[standard]`, `apscheduler`  
**Storage**: Filesystem only — `ARIAscans/` (watch), `ARIAscans/in-progress/` (claimed), `ARIAscans/processed/` (done); in-memory `BatchRunState` for dashboard  
**Testing**: `pytest` + `pytest-asyncio`; httpx for FastAPI test client; `pytest-cov` for coverage  
**Target Platform**: macOS 13+ (Ventura), MedPath Wi-Fi, SMB-mounted ARIA share at `/Volumes/aria/ARIAscans`  
**Project Type**: Background daemon + embedded web server (macOS LaunchAgent)  
**Performance Goals**: Upload start within 60 s of file arrival; dashboard refresh ≤ 3 s per page completion  
**Constraints**: Single process (web server + scheduler); no Docker at runtime; no database; atomic file moves on SMB volume  
**Scale/Scope**: Small-office scanner; expected ≤ 20 PDFs/day, ≤ 50 pages each

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Status | Notes |
|-----------|--------|-------|
| I. macOS-First Unattended Operation | ✅ Pass | Constitution v2.0.0 — macOS is now the canonical deployment target. launchd `KeepAlive` + `WaitForPaths` satisfies restart-on-crash and mount-dependency requirements. |
| II. Test-Driven Development | ✅ Required | No tests exist yet. All new modules must follow Red → Green → Refactor. Failing test commit must predate implementation commit. |
| III. Quality First | ✅ Required | `ruff`, `mypy --strict`, ≥ 90% coverage enforced. |
| IV. Observability & Structured Logging | ✅ Required | Log every file claimed, every page upload attempt/outcome, every rotation applied, every crash-recovery event. Redact `api_token`. |
| V. Documentation Before PR | ✅ Required | `README.md`, `.env.example`, and `docs/launchd-setup.md` must be current before PR. |

## Project Structure

### Documentation (this feature)

```text
specs/003-we-watch-all/
├── plan.md              ← this file
├── research.md          ← Phase 0 output
├── data-model.md        ← Phase 1 output
├── quickstart.md        ← Phase 1 output
├── contracts/           ← Phase 1 output
│   ├── upload-endpoint.md
│   └── dashboard-api.md
└── tasks.md             ← Phase 2 output (/speckit-tasks — not created here)
```

### Source Code (repository root)

```text
scanner/
├── __main__.py          # Entry: wire FastAPI app + APScheduler, start uvicorn
├── config.py            # Updated Settings — add dashboard_port, cron_interval_seconds; increase file_settle_seconds default to 10
├── state.py             # Thread-safe BatchRunState, FileResult, PageResult dataclasses + Lock
├── pdf_processor.py     # PDF → per-page PIL images with orientation correction (PyMuPDF + pytesseract OSD fallback)
├── uploader.py          # Single-page HTTP upload (extracted + simplified from watcher.py)
├── batch.py             # Batch runner: crash recovery → scan → settle filter → claim → process → move
└── dashboard.py         # FastAPI app: GET / (HTML), GET /status (JSON), GET /events (SSE), POST /run (manual trigger)

docs/
└── launchd-setup.md     # One-time macOS daemon installation instructions

launchd/
└── io.mpsinc.pms-scanner.plist   # LaunchAgent plist template

tests/
├── unit/
│   ├── test_config.py           # Settings parsing, env var defaults
│   ├── test_state.py            # Thread-safety of BatchRunState mutations
│   ├── test_pdf_processor.py    # Rotation correction logic (mock pymupdf pages)
│   ├── test_uploader.py         # Upload success/failure/retry (mock requests)
│   └── test_batch.py            # Claim logic, settle filter, crash recovery, folder moves
├── integration/
│   ├── test_batch_integration.py   # Full run against tmp folder + mock HTTP server
│   └── test_dashboard_integration.py  # SSE stream + /status endpoint via httpx
└── contract/
    └── test_upload_contract.py  # POST /api/scanned-images/upload schema validation
```

**Structure Decision**: Single-project layout extending the existing `scanner/` package. `watcher.py` is retired and replaced by `batch.py` + `dashboard.py`. All new modules are siblings inside `scanner/`.

## Complexity Tracking

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|--------------------------------------|
| Embedded web server (FastAPI in daemon process) | Dashboard must reflect in-memory progress state updated by the batch runner; a separate process would require IPC or a shared file, adding complexity | Separate dashboard process: requires JSON file polling or a message queue; a single process with shared in-memory state is simpler and avoids race conditions |
