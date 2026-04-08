# Tasks: Folder Monitor and File Upload

**Input**: Design documents from `specs/001-folder-monitor-upload/`  
**Branch**: `001-folder-monitor-upload`  
**Generated**: 2026-04-08

**TDD Note**: The project constitution (Principle II) mandates TDD without exception. All test tasks MUST be committed and confirmed failing before their paired implementation tasks begin.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no blocking dependency)
- **[Story]**: User story this task belongs to ([US1], [US2], [US3])

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Install tooling and create the test skeleton. No implementation may begin until this phase is complete.

- [x] T001 Create `pyproject.toml` with ruff, mypy --strict, pytest, and pytest-cov configuration (`pyproject.toml`)
- [x] T002 [P] Create `requirements-dev.txt` with dev dependencies: pytest, pytest-cov, responses, pytest-mock, ruff, mypy (`requirements-dev.txt`)
- [x] T003 [P] Add `tenacity>=8.0` to `requirements.txt` (`requirements.txt`)
- [x] T004 Create tests skeleton: `tests/__init__.py`, `tests/unit/__init__.py`, `tests/integration/__init__.py`, `tests/contract/__init__.py`, `tests/conftest.py`

**Checkpoint**: `pip install -r requirements-dev.txt` succeeds; `pytest` discovers zero tests and exits 0; `ruff check .` and `mypy --strict scanner/` run without crashing.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Validate the existing config module and establish the upload contract test. These MUST be green before any user story work.

⚠️ **CRITICAL**: Write tests first — confirm they FAIL — then implement fixes.

- [x] T005 Write failing unit tests for `Settings` in `tests/unit/test_config.py`: required fields raise `ValidationError` when absent (`BACKEND_UPLOAD_URL`, `API_TOKEN`), all defaults are correct, env vars are loaded case-insensitively
- [x] T006 Run `mypy --strict scanner/config.py` and `ruff check scanner/config.py`; fix any type annotation or linting violations in `scanner/config.py` until T005 passes
- [x] T007 [P] Write failing contract test in `tests/contract/test_upload_contract.py`: mock a successful POST and assert (a) `Authorization: Bearer {token}` header is present, (b) `file` multipart part contains filename and MIME type, (c) `folder` multipart part is a string — per `contracts/backend-upload.md`

**Checkpoint**: `pytest tests/unit/test_config.py tests/contract/` — all tests pass; `mypy --strict scanner/config.py` — zero errors.

---

## Phase 3: User Story 1 — File Automatically Uploaded After Detection (P1) 🎯 MVP

**Goal**: A file dropped in the watch folder is detected, settled for 0.5 s, uploaded to the backend with Bearer auth, then moved to `processed/`.

**Independent Test**: Drop a single image into the watch folder against a mock HTTP server; confirm within 5 s that (a) the backend received a valid multipart POST, (b) the file exists in `processed/`, (c) the file is gone from the watch root.

> ⚠️ **Write ALL tests in this section first. Confirm each FAILS. Then implement.**

### Tests — User Story 1

- [x] T008 [P] [US1] Write failing unit tests for `is_image()` in `tests/unit/test_watcher.py`: supported extensions (`.jpg`, `.jpeg`, `.png`, `.gif`, `.bmp`, `.tiff`, `.webp`) return `True`; unsupported (`.pdf`, `.txt`, no extension) return `False`; case-insensitive (`.JPG`)
- [x] T009 [P] [US1] Write failing unit tests for `upload_image()` happy path in `tests/unit/test_upload.py`: 2xx response returns `True`; auth header `Bearer {token}` is present; `folder` field equals relative path from watch root; returned `UploadResult.destination_path` points inside `processed/`
- [x] T010 [P] [US1] Write failing integration test in `tests/integration/test_watcher_integration.py`: create a temp watch dir, start observer, copy an image in, assert within 3 s that mock HTTP server received one POST and the file was moved to `processed/`

### Implementation — User Story 1

- [x] T011 [US1] Refactor `scanner/watcher.py`: replace blocking event handler with `queue.Queue` producer; add dedicated worker thread that (1) waits `file_settle_seconds`, (2) calls `upload_image()`, (3) moves file to `processed/` on success; add 2-second deduplication seen-set keyed on resolved path to prevent duplicate events; create a per-thread `requests.Session`
- [x] T012 [US1] Add `tenacity` retry to `upload_image()` in `scanner/watcher.py`: `stop_after_attempt(3)`, `wait_exponential(multiplier=1, min=1, max=10) + wait_random(0, 1)`, retry on `requests.RequestException` and HTTP 5xx; log each retry via `before_sleep`; do NOT retry on 4xx; ensure `UploadResult` returned with `destination_path` set on success
- [x] T013 [US1] Update `scanner/watcher.py` `run()`: auto-create watch dir and `processed/` subfolder (`mkdir(parents=True, exist_ok=True)`); exclude `processed/` from watchdog event scope (filter by path prefix); register `signal.SIGTERM` handler that sets a shutdown event and calls `observer.stop()`; drain the queue before exit
- [x] T014 [US1] Update `scanner/__main__.py`: log startup configuration at INFO level with `api_token` redacted to first 4 chars + `***`; register `signal.SIGTERM` handler to trigger graceful shutdown

**Checkpoint**: `pytest tests/unit/ tests/integration/ tests/contract/` — all green; place an image in `incoming/` with a running service (or integration test temp dir) — file appears in `processed/` within 5 s.

---

## Phase 4: User Story 2 — Upload Failure Is Captured and Surfaced (P2)

**Goal**: When the backend is unreachable or returns an error, the failure is logged with the file name and error detail; the file remains in the watch root; the service keeps running.

**Independent Test**: Simulate a backend that always returns 503; drop a file; assert after retries that (a) at least one `ERROR` log line includes the filename, (b) the file is still in the watch root (not in `processed/`), (c) the observer is still alive.

> ⚠️ **Write ALL tests first. Confirm each FAILS. Then implement.**

### Tests — User Story 2

- [x] T015 [P] [US2] Write failing unit tests for `upload_image()` failure path in `tests/unit/test_upload.py`: HTTP 4xx → returns `UploadResult(success=False)`; HTTP 5xx → retried 3 times → returns `UploadResult(success=False)`; network error → retried 3 times → returns `UploadResult(success=False)`; all failure cases include non-null `error_message`
- [x] T016 [P] [US2] Write failing unit test in `tests/unit/test_watcher.py`: when `upload_image()` returns `success=False`, the file is NOT moved (still in watch root); error is logged at ERROR level with file name and reason
- [x] T017 [P] [US2] Write failing integration test in `tests/integration/test_watcher_integration.py`: configure mock server to return 503; drop a file; assert service continues monitoring (observer thread alive) and a second file dropped afterwards is processed normally

### Implementation — User Story 2

- [x] T018 [US2] In `scanner/watcher.py` worker thread: after `upload_image()` returns `success=False`, log at ERROR level (`"Upload failed for %s after %d attempts: %s"`) and leave file in place; do NOT move to `processed/`; ensure worker loop continues to next queued item without crashing

**Checkpoint**: `pytest tests/unit/ tests/integration/` — all green including failure-path tests.

---

## Phase 5: User Story 3 — Multiple Files Processed Without Loss (P3)

**Goal**: A burst of 10 files arriving simultaneously are each independently uploaded and moved to `processed/`; none are skipped or deduplicated incorrectly.

**Independent Test**: Drop 10 distinct image files into the watch folder within 1 second; assert all 10 appear in `processed/` and the mock server received exactly 10 POSTs.

> ⚠️ **Write ALL tests first. Confirm each FAILS. Then implement.**

### Tests — User Story 3

- [x] T019 [P] [US3] Write failing unit test for deduplication seen-set in `tests/unit/test_watcher.py`: same path within 2 s → queued only once; same path after 2 s → queued again (distinct files with distinct paths are always queued independently)
- [x] T020 [P] [US3] Write failing integration test in `tests/integration/test_watcher_integration.py`: drop 10 distinct image files within 1 s; assert mock server received exactly 10 POSTs and all 10 files are in `processed/` within 15 s

### Implementation — User Story 3

- [x] T021 [US3] Verify that the queue worker from T011 handles burst correctly; if the deduplication seen-set incorrectly suppresses distinct files, fix the key logic in `scanner/watcher.py` (key must be resolved absolute path, not just filename); use a bounded queue (`queue.Queue(maxsize=100)`) to guard against unbounded memory under extreme load

**Checkpoint**: `pytest tests/integration/test_watcher_integration.py` — burst test passes with all 10 files processed.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Quality gates, documentation, and final validation per the project constitution.

- [x] T022 Run `ruff check . && ruff format --check .` across the entire repo; fix all linting and formatting violations (`scanner/`, `tests/`)
- [x] T023 Run `mypy --strict scanner/` and fix all type errors; ensure `watcher.py` fully type-annotated including `queue.Queue[Path]`, `threading.Event`, `threading.Thread`
- [x] T024 Run `pytest --cov=scanner --cov-report=term-missing`; verify coverage ≥ 90% on all scanner modules; add targeted unit tests for any uncovered branches
- [x] T025 [P] Create `README.md`: project overview, env var table (all 7 variables, required/optional, defaults), Docker quickstart, `processed/` and failure-retention behaviour, volume mapping notes (`incoming/` → `/data/incoming`)
- [x] T026 [P] Update `quickstart.md` in `specs/001-folder-monitor-upload/` if any commands or env vars changed during implementation
- [x] T027 Perform final end-to-end smoke test per `specs/001-folder-monitor-upload/quickstart.md`: `docker compose up --build`, drop 3 test images, confirm all appear in `processed/`, check logs for startup config line and upload success lines

**Checkpoint**: All quality gates pass — `ruff check .` ✅, `mypy --strict scanner/` ✅, `pytest --cov=scanner` ✅ (≥90%), `README.md` present and accurate.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1 (Setup)**: No dependencies — start immediately
- **Phase 2 (Foundational)**: Depends on Phase 1 — blocks all user stories
- **Phase 3 (US1)**: Depends on Phase 2 — write tests first, confirm fail, then implement
- **Phase 4 (US2)**: Depends on Phase 3 implementation — failure path builds on the upload function
- **Phase 5 (US3)**: Depends on Phase 3 implementation — concurrency builds on the queue worker
- **Phase 6 (Polish)**: Depends on Phases 3–5 complete

### Within Each User Story

1. Write all tests for the story → confirm each FAILS
2. Implement in order: config/helpers → core logic → worker integration → lifecycle
3. Run tests → confirm all PASS
4. Commit with message: `test: [US?] <what the test verifies>` before `feat: [US?] <what was implemented>`

### Parallel Opportunities

- T002, T003 can run in parallel with T001 (different files)
- T007 can run in parallel with T005/T006 (different test file)
- T008, T009, T010 can all be written in parallel (different files)
- T015, T016, T017 can be written in parallel (different test scenarios)
- T019, T020 can be written in parallel
- T022, T025, T026 can run in parallel (different files)

---

## Parallel Example: User Story 1 Test Writing

```
Simultaneously write (different files, no conflicts):
  T008 → tests/unit/test_watcher.py  (is_image tests)
  T009 → tests/unit/test_upload.py   (upload_image happy path)
  T010 → tests/integration/test_watcher_integration.py
```

---

## Implementation Strategy

### MVP (User Story 1 Only — P1)

1. Complete Phase 1: Setup
2. Complete Phase 2: Foundational — config tests + contract test
3. Write T008, T009, T010 → confirm all FAIL
4. Complete T011–T014 → confirm all PASS
5. **STOP and VALIDATE**: `docker compose up --build`, drop one image, confirm it lands in `processed/`
6. This alone satisfies FR-001 through FR-004 and FR-008

### Incremental Delivery

1. MVP: US1 → files reliably uploaded and moved to `processed/`
2. Add US2 → failures logged; service resilient to backend outages
3. Add US3 → burst handling verified; no file loss
4. Polish → quality gates, README, smoke test

---

## Task Count Summary

| Phase | Tasks | Test Tasks | Impl Tasks |
|-------|-------|------------|------------|
| Phase 1: Setup | 4 | — | 4 |
| Phase 2: Foundational | 3 | 2 (T005, T007) | 1 (T006) |
| Phase 3: US1 | 7 | 3 (T008–T010) | 4 (T011–T014) |
| Phase 4: US2 | 4 | 3 (T015–T017) | 1 (T018) |
| Phase 5: US3 | 3 | 2 (T019–T020) | 1 (T021) |
| Phase 6: Polish | 6 | 1 (T024) | 5 |
| **Total** | **27** | **11** | **16** |
