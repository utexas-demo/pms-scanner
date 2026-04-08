# Implementation Plan: Folder Monitor and File Upload

**Branch**: `001-folder-monitor-upload` | **Date**: 2026-04-08 | **Spec**: [spec.md](spec.md)  
**Input**: Feature specification from `specs/001-folder-monitor-upload/spec.md`

## Summary

Implement a reliable, unattended file-monitoring and upload service for pms-scanner. The service watches a configurable local folder (auto-creating it if absent), detects new image files via watchdog, waits 0.5 seconds for write stabilisation, then uploads each file to the configured backend endpoint using a hardcoded Bearer token. On confirmed upload, the file is moved to a `processed/` subfolder for audit and to prevent re-upload on restart. Failed uploads are retried up to 3 times with exponential back-off (tenacity); files that exhaust retries remain in the watch root so they are automatically re-attempted on the next service restart. A queue-based worker thread decouples detection from upload to prevent event loss under burst conditions. All outcomes are logged with structured context. SIGTERM is handled for graceful Docker shutdown.

## Technical Context

**Language/Version**: Python 3.12 (from `Dockerfile`)  
**Primary Dependencies**: watchdog ≥4.0, requests ≥2.31, pydantic-settings ≥2.2, python-dotenv ≥1.0, tenacity ≥8.0 (new)  
**Storage**: File system only (watched folder; no database)  
**Testing**: pytest, pytest-cov, responses (HTTP mock), pytest-mock  
**Target Platform**: Linux container (python:3.12-slim) running on Windows via Docker Desktop; NSSM as alternative for native Windows install  
**Project Type**: Background service / daemon  
**Performance Goals**: Files uploaded within 5 seconds of detection (SC-001); bursts of 10 simultaneous files without loss (SC-003)  
**Constraints**: 0.5s settle delay (FR-002); 30s HTTP timeout; single instance per machine; no offline-first requirement  
**Scale/Scope**: Single-machine unattended service; scanner-throughput file volume (low to moderate)

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-checked after Phase 1 design — see bottom of this section.*

### Principle I — Windows-First, Unattended Operation

| Requirement | Status | Resolution |
|-------------|--------|------------|
| `restart: unless-stopped` supervisor | ✅ Present | `docker-compose.yml` already configured |
| No hard-coded Windows paths in source | ✅ Pass | All paths via env vars (`WATCH_DIR`) |
| Retry logic with exponential back-off | ❌ Missing | **Add**: `tenacity` retry decorator in `upload_image()` |
| Recover from transient I/O errors | ❌ Missing | **Add**: file-exist guard before upload; queue absorbs watchdog blocking |
| SIGTERM / SIGINT handled; graceful shutdown | ⚠️ Partial | `KeyboardInterrupt` caught; **Add**: `signal.SIGTERM` handler + drain queue |
| Startup config logged (secrets redacted) | ❌ Missing | **Add**: log config at INFO in `__main__.py`; redact `api_token` |

### Principle II — TDD (NON-NEGOTIABLE)

| Requirement | Status | Resolution |
|-------------|--------|------------|
| Tests exist | ❌ **GATE FAIL** | **Must add** `tests/` before any implementation; test-first task ordering enforced in tasks |
| Failing test precedes implementation | ❌ Not enforced yet | Enforced via task ordering in `/speckit.tasks` |

**Gate override**: No implementation exists yet — the scaffold is empty. The gate applies to this feature's implementation work, which will follow TDD. All task slices in `tasks.md` will be ordered: test first, then implementation.

### Principle III — Quality First

| Requirement | Status | Resolution |
|-------------|--------|------------|
| ruff (linting + formatting) | ❌ Not configured | **Add**: `pyproject.toml` with ruff config |
| mypy --strict | ❌ Not configured | **Add**: mypy config in `pyproject.toml` |
| Coverage ≥ 90% | ❌ Not measured | **Add**: pytest-cov; coverage target in CI note |

### Principle IV — Observability & Structured Logging

| Requirement | Status | Resolution |
|-------------|--------|------------|
| Correct log format | ✅ Present | `%(asctime)s [%(levelname)s] %(name)s: %(message)s` in `__main__.py` |
| Upload attempt/outcome logged | ✅ Present | `watcher.py` logs success and errors |
| Startup config logged (token redacted) | ❌ Missing | **Add** in `__main__.py` |
| Retry events logged | ❌ Missing | **Add**: tenacity `before_sleep` callback |
| File detection logged | ⚠️ Partial | No explicit detection log; **Add** `logger.debug("Detected %s", path)` |

### Principle V — Documentation Before PR

| Requirement | Status | Resolution |
|-------------|--------|------------|
| README.md current | ❌ Missing | **Add**: `README.md` with env var table, Docker instructions, volume mapping |
| Docs updated before PR | ❌ Not applicable yet | Enforced at PR stage |

### Post-Phase-1 Re-evaluation

All violations are addressed by planned deliverables within this feature. No structural design conflicts with the constitution. No gate blocks planning.

---

## Project Structure

### Documentation (this feature)

```text
specs/001-folder-monitor-upload/
├── plan.md              ✅ This file
├── research.md          ✅ Phase 0 complete
├── data-model.md        ✅ Phase 1 complete
├── quickstart.md        ✅ Phase 1 complete
├── contracts/
│   └── backend-upload.md  ✅ Phase 1 complete
├── checklists/
│   └── requirements.md  ✅ Spec validation complete
└── tasks.md             ⏳ Phase 2 — created by /speckit.tasks
```

### Source Code (repository root)

```text
scanner/
├── __main__.py          # Entry point: logging setup, SIGTERM handler, startup config log
├── config.py            # pydantic-settings Settings; env var config
└── watcher.py           # Watchdog observer, queue worker, upload with retry, file disposition (move to processed/ on success; leave in place on failure)

tests/
├── unit/
│   ├── test_config.py   # Settings validation, defaults, required fields
│   ├── test_watcher.py  # is_image(), deduplication, queue logic, retry behaviour, file disposition (move on success, leave on failure)
│   └── test_upload.py   # upload_image() success, HTTP errors, network errors, processed/ move
├── integration/
│   └── test_watcher_integration.py  # Full observer lifecycle against temp dir + mock HTTP server
└── contract/
    └── test_upload_contract.py      # Validates multipart shape and auth header against contract spec

pyproject.toml           # ruff, mypy, pytest, coverage configuration
requirements.txt         # Runtime dependencies (add tenacity)
requirements-dev.txt     # Dev dependencies: pytest, pytest-cov, responses, pytest-mock, ruff, mypy
README.md                # New: operational guide, env var table, Docker instructions
```

**Structure Decision**: Single project layout. No frontend or API server — this is a pure background daemon. `scanner/` is the sole source package. Tests are co-located in `tests/` at repo root following standard Python conventions.

## Complexity Tracking

No constitution violations requiring justification. All identified gaps are standard additions (retry library, test suite, tooling config, README) — none increase architectural complexity.
