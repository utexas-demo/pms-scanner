---
description: "Task list for 003: PDF batch processing, cron scheduling, progress dashboard"
---

# Tasks: PDF Scan Batch Processing with Cron Scheduling and Progress Dashboard

**Input**: Design documents from `specs/003-we-watch-all/`
**Prerequisites**: plan.md ✅ | spec.md ✅ | research.md ✅ | data-model.md ✅ | contracts/ ✅

**TDD REQUIRED**: Constitution Principle II is non-negotiable. Every test task MUST be
committed and confirmed failing before its paired implementation task is started.

## Format: `[ID] [P?] [Story?] Description — file path`

- **[P]**: Safe to run in parallel (different files, no incomplete dependencies)
- **[US#]**: Traces to User Story from spec.md

---

## Phase 1: Setup

**Purpose**: Project scaffolding and tooling — no user story work yet.

- [X] T001 Update `requirements.txt` — remove `watchdog`; add `pymupdf`, `Pillow`, `pytesseract`, `fastapi`, `uvicorn[standard]`, `apscheduler`, `tenacity` (retry back-off); add test-only group: `httpx`, `pytest-asyncio`, `pytest-cov`, `pytest-httpserver`
- [X] T002 [P] Create `tests/` directory tree with empty `__init__.py` files — `tests/unit/`, `tests/integration/`, `tests/contract/`
- [X] T003 [P] Add `pyproject.toml` — configure `ruff` (lint + format), `mypy --strict` for `scanner/`, and `pytest` (testpaths, asyncio_mode)
- [X] T004 [P] Create `launchd/` and `docs/` directories at repo root (empty, ready for US3 artifacts)

---

## Phase 2: Foundational

**Purpose**: Shared infrastructure every user story depends on. BLOCKS all story phases.

**⚠️ CRITICAL**: No user story work may begin until this phase is complete.

- [X] T005 [P] Write failing unit tests for `Settings` — `tests/unit/test_config.py`: assert `cron_interval_seconds` defaults to 60, `dashboard_port` to 8080, `file_settle_seconds` to 10.0, `inprogress_dir` and `processed_dir` are derived correctly from `watch_dir`
- [X] T006 [P] Write failing unit tests for state dataclasses — `tests/unit/test_state.py`: assert `AppState` initialises with `current_run=None`, `last_run=None`; assert `threading.Lock` prevents concurrent mutation; assert `PageResult`, `FileResult`, `BatchRunState` fields and defaults
- [X] T007 [P] Write failing unit tests for uploader — `tests/unit/test_uploader.py`: assert successful POST returns `True`; assert HTTP 4xx/5xx returns `False` and logs error; assert per-page filename convention `{stem}_p{num:03d}.jpg`; assert transient 5xx triggers retry (mock returns 503 twice then 200 — expect 3 calls); assert retry stops after max attempts and returns `False`; use `unittest.mock` to stub `requests.post`
- [X] T008 Update `scanner/config.py` — add `cron_interval_seconds: int = 60`, `dashboard_port: int = 8080`; change `file_settle_seconds` default to `10.0`; add `@property inprogress_dir` and `@property processed_dir` returning `Path(watch_dir) / "in-progress"` and `Path(watch_dir) / "processed"` — `scanner/config.py`
- [X] T009 [P] Create `scanner/state.py` — `PageResult`, `FileResult`, `BatchRunState`, `AppState` dataclasses per `data-model.md`; `AppState` wraps a `threading.Lock`; expose `app_state` singleton — `scanner/state.py`
- [X] T010 [P] Delete `scanner/watcher.py` (retire watchdog-based watcher; its upload logic migrates to `scanner/uploader.py`)
- [X] T011 Create `scanner/uploader.py` — extract and adapt upload logic from the deleted `watcher.py`; function `upload_page(path: Path, page_num: int, total_pages: int, image: Image) -> bool`; derive filename as `{path.stem}_p{page_num:03d}.jpg`; POST to `{backend_base_url}/api/scanned-images/upload`; return `bool` — `scanner/uploader.py`
- [X] T035 [P] Write failing unit tests for graceful shutdown — `tests/unit/test_main.py`: assert that sending SIGTERM stops the APScheduler (mock `scheduler.shutdown(wait=True)`); assert no `SystemExit` is raised mid-upload (mock an in-flight thread); use `signal.raise_signal(signal.SIGTERM)` or `os.kill(os.getpid(), signal.SIGTERM)` in test
- [X] T036 Implement retry with exponential back-off in `scanner/uploader.py` — decorate `upload_page()` with `@tenacity.retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=10), retry=retry_if_exception_type(requests.RequestException), reraise=False)`; on final failure log ERROR and return `False`; add `UPLOAD_MAX_RETRIES` and `UPLOAD_RETRY_MAX_WAIT_SECONDS` to `scanner/config.py` — `scanner/uploader.py`, `scanner/config.py`
- [X] T037 Implement SIGTERM/SIGINT graceful shutdown in `scanner/__main__.py` — register `signal.signal(SIGTERM, _shutdown)` and `signal.signal(SIGINT, _shutdown)`; `_shutdown()` calls `scheduler.shutdown(wait=True)` (waits for in-flight batch threads to complete) then calls `sys.exit(0)`; log "Graceful shutdown initiated" at INFO on receipt — `scanner/__main__.py`

**Checkpoint**: `pytest tests/unit/test_config.py tests/unit/test_state.py tests/unit/test_uploader.py tests/unit/test_main.py` must all pass before proceeding.

---

## Phase 3: User Story 1 — Scheduled PDF Batch Upload (Priority: P1) 🎯 MVP

**Goal**: Every PDF in the watch folder is processed and all pages uploaded on each cron tick.

**Independent Test**: Drop 2 PDFs (one with rotated pages) into `/Volumes/aria/ARIAscans/`, wait ≤ 60 s, verify all pages appear correctly oriented in backend and both files move to `ARIAscans/processed/`.

### Tests for User Story 1 ⚠️ WRITE FIRST — confirm failure before T016

- [X] T012 [P] [US1] Write failing unit tests for `pdf_processor` — `tests/unit/test_pdf_processor.py`: assert page count returned correctly; assert `page.rotation != 0` triggers correction; assert pytesseract fallback called when PDF rotation is 0; assert `orientation_uncertain=True` flagged when both tiers fail; mock `fitz.open` and `pytesseract.image_to_osd`
- [X] T013 [P] [US1] Write failing unit tests for `batch` runner — `tests/unit/test_batch.py`: assert crash-recovery moves all `in-progress/` files back to watch folder at run start; assert settle filter skips files modified within `file_settle_seconds`; assert `Path.rename()` called for atomic claim; assert failed file returned to watch folder; assert successful file moved to `processed/`; use `tmp_path` fixture
- [X] T014 [P] [US1] Write failing integration test for full batch run — `tests/integration/test_batch_integration.py`: create temp dir mimicking `ARIAscans/` with a real 2-page PDF; run `batch.execute_run()`; assert both pages posted to mock HTTP server; assert PDF in `processed/`; use `pytest-httpserver` or `unittest.mock`
- [X] T015 [P] [US1] Write failing contract test for upload endpoint — `tests/contract/test_upload_contract.py`: POST a JPEG to `{BACKEND_BASE_URL}/api/scanned-images/upload` with Bearer token; assert response has `batch_id`, `images[]`, `rejected[]` keys; skip if `BACKEND_BASE_URL` not set (mark `pytest.mark.skipif`)

### Implementation for User Story 1

- [X] T016 [P] [US1] Create `scanner/pdf_processor.py` — `process_pdf(path: Path) -> list[tuple[int, Image, bool, int]]` returning `(page_num, pil_image, orientation_uncertain, rotation_applied)` per page; tier 1: read `page.rotation` via PyMuPDF; tier 2: pytesseract OSD fallback; convert page to PIL via `page.get_pixmap().pil_tobytes()`; **log at DEBUG**: page count on open; rotation applied per page; **log at WARNING**: `orientation_uncertain=True` cases — `scanner/pdf_processor.py`
- [X] T017 [US1] Create `scanner/batch.py` — `execute_run(state: AppState) -> None`; step 1: move all files from `inprogress_dir` back to `watch_dir` (crash recovery, FR-016); step 2: scan `watch_dir` for `*.pdf`, filter by settle window (FR-001); if `watch_dir` does not exist log ERROR and return (FR-012); step 3: for each PDF, atomically claim via `Path.rename()` to `inprogress_dir` (catch `FileNotFoundError` for lost-race — skip); step 4: call `pdf_processor.process_pdf()`; step 5: call `uploader.upload_page()` per page; step 6: on full success move to `processed_dir`, on any failure return to `watch_dir`; update `state` under lock throughout; **log at INFO**: run start/end, each file claimed, each file completed; **log at ERROR**: upload failures (with filename, page num, HTTP status); **log at WARNING**: files returned to watch after failure — `scanner/batch.py`
- [X] T018 [US1] Update `scanner/__main__.py` — instantiate `AppState`; create `APScheduler BackgroundScheduler` with `ThreadPoolExecutor(max_workers=4)`; schedule `execute_run` every `settings.cron_interval_seconds`; start scheduler; keep process alive (replaced `while True: sleep(1)` from old watcher) — `scanner/__main__.py`
- [X] T019 [US1] Ensure `inprogress_dir` and `processed_dir` created at startup in `scanner/batch.py` `startup()` function called from `__main__.py` before scheduler starts — `scanner/batch.py`

**Checkpoint**: `pytest tests/unit/test_pdf_processor.py tests/unit/test_batch.py tests/integration/test_batch_integration.py` all pass. Drop a PDF manually — confirm it lands in `processed/` within 60 s.

---

## Phase 4: User Story 2 — Live Progress Dashboard (Priority: P2)

**Goal**: Browser-accessible dashboard shows real-time filename + page X/Y during active runs; last-run summary when idle.

**Independent Test**: Start the app, navigate to `http://localhost:8080`, drop a 20-page PDF, watch the counter advance page-by-page without refreshing.

### Tests for User Story 2 ⚠️ WRITE FIRST — confirm failure before T022

- [X] T020 [P] [US2] Extend `tests/unit/test_state.py` — assert `AppState.to_status_dict()` serialises `current_run` and `last_run` correctly; assert SSE event payload shape for `run_started`, `file_started`, `page_done`, `file_done`, `run_done` matches `contracts/dashboard-api.md`
- [X] T021 [P] [US2] Write failing integration tests for dashboard — `tests/integration/test_dashboard_integration.py`: use `httpx.AsyncClient` with `app` fixture; assert `GET /` returns HTML 200; assert `GET /status` JSON has `current_run` and `last_run` keys; assert `GET /healthz` returns `{"status": "ok"}`; assert `POST /run` returns 202 with `run_id`; assert `GET /events` streams `text/event-stream`

### Implementation for User Story 2

- [X] T022 [P] [US2] Create `scanner/dashboard.py` — FastAPI app; inject `AppState` via dependency; `GET /` serves inline HTML; `GET /status` returns `app_state.to_status_dict()` as JSON; `GET /events` yields SSE heartbeat every 15 s + events pushed from state; `POST /run` submits `execute_run` to scheduler thread pool immediately; `GET /healthz` returns `{"status": "ok"}`; **log at INFO**: each `/run` trigger (manual vs scheduled); **log at DEBUG**: each SSE client connect/disconnect — `scanner/dashboard.py`
- [X] T023 [US2] Add inline dashboard HTML to `scanner/dashboard.py` — single-page HTML string returned by `GET /`; JavaScript `EventSource('/events')` subscribes; on `page_done` event updates `<span id="filename">` and `<span id="progress">`; on `run_done` shows summary; styles kept minimal (no build step) — `scanner/dashboard.py`
- [X] T024 [US2] Update `scanner/__main__.py` — import `dashboard.app`; pass shared `AppState` instance to both `batch.execute_run` (scheduler) and `dashboard.app` (FastAPI state); start uvicorn on `settings.dashboard_port` in the main thread (uvicorn blocks); APScheduler starts before uvicorn — `scanner/__main__.py`
- [X] T025 [US2] Add `AppState.emit_event()` and `AppState.to_status_dict()` methods to `scanner/state.py`; `emit_event()` appends to an `asyncio.Queue` polled by the SSE endpoint; `to_status_dict()` returns a JSON-serialisable dict snapshot under lock — `scanner/state.py`

**Checkpoint**: `pytest tests/unit/ tests/integration/test_dashboard_integration.py` all pass. Start app locally, open browser — verify real-time progress updates.

---

## Phase 5: User Story 3 — macOS-Native Operation (Priority: P3)

**Goal**: One-time setup installs the scanner as a launchd daemon; it survives reboots and waits for the SMB share before starting.

**Independent Test**: Install plist, reboot Mac, verify daemon restarts automatically, verify dashboard accessible within 60 s of login (after SMB share mounts).

### Implementation for User Story 3

- [X] T026 [P] [US3] Create `launchd/io.mpsinc.pms-scanner.plist` — LaunchAgent with `KeepAlive: true`; `WaitForPaths: ["/Volumes/aria/ARIAscans"]`; `ProgramArguments` points to `.venv/bin/python -m scanner`; `WorkingDirectory` is repo root; `StandardOutPath`/`StandardErrorPath` to `/tmp/pms-scanner.log`; `EnvironmentVariables` loads path (not secrets — those come from `.env`) — `launchd/io.mpsinc.pms-scanner.plist`
- [X] T027 [P] [US3] Create `docs/launchd-setup.md` — installation steps: customise plist paths, `launchctl load`, `launchctl list` verification, log tail; SMB auto-mount instructions; unload instructions; troubleshooting table — `docs/launchd-setup.md`
- [X] T028 [P] [US3] Update `.env.example` — add `CRON_INTERVAL_SECONDS=60`, `DASHBOARD_PORT=8080`; update `FILE_SETTLE_SECONDS` default comment to `10` (was `0.5`); add `WATCH_DIR=/Volumes/aria/ARIAscans` as the concrete default — `.env.example`
- [X] T029 [US3] Update `README.md` — add macOS deployment section; document all new env vars (`CRON_INTERVAL_SECONDS`, `DASHBOARD_PORT`); document folder lifecycle (`in-progress/`, `processed/`); link to `docs/launchd-setup.md`; update quickstart to use `python -m scanner` instead of Docker — `README.md`

**Checkpoint**: Fresh macOS machine (or VM). Follow `docs/launchd-setup.md` start-to-finish. Reboot. Confirm daemon running and dashboard reachable.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Quality gates and final validation across all stories.

- [X] T030 [P] Run `ruff check . --fix` and resolve any remaining violations — all `scanner/` and `tests/` files
- [X] T031 [P] Run `mypy --strict scanner/` and resolve all type errors — all `scanner/` files
- [X] T032 [P] Run `pytest --cov=scanner --cov-report=term-missing` — confirm ≥ 90% coverage on all non-trivial modules; add targeted unit tests to reach threshold if needed
- [ ] T033 Run quickstart end-to-end validation per `specs/003-we-watch-all/quickstart.md` — mount share, drop PDF, watch dashboard, confirm `processed/`
- [X] T034 [P] Update `CLAUDE.md` — add all new dependencies (pymupdf, Pillow, pytesseract, fastapi, uvicorn, apscheduler) and launchd service details

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1 (Setup)**: No dependencies — start immediately; all tasks parallelisable
- **Phase 2 (Foundational)**: Depends on Phase 1 — **BLOCKS** all story phases; T005–T007 (tests) must precede T008–T011 (implementations) within the phase
- **Phase 3 (US1)**: Depends on Phase 2 complete — T012–T015 (tests) must precede T016–T019 (implementation)
- **Phase 4 (US2)**: Depends on Phase 2 complete; T020–T021 (tests) must precede T022–T025 (implementation); integrates with Phase 3 `AppState`
- **Phase 5 (US3)**: Depends on Phase 3 complete (needs working app to test install); all tasks parallelisable within phase
- **Phase 6 (Polish)**: Depends on all user story phases complete

### Within Each User Story

```
Tests (MUST FAIL first) → Models/State → Services → Wiring → Checkpoint
```

### Parallel Opportunities

**Phase 1** — all four tasks in parallel:
```
T001 (requirements)  T002 (tests dirs)  T003 (pyproject)  T004 (launchd/docs dirs)
```

**Phase 2** — tests first, then implementations in parallel:
```
T005 [P]  T006 [P]  T007 [P]  T035 [P]   ← all failing tests committed
    ↓
T008      T009 [P]  T010 [P]  T011
    ↓
T036      T037                             ← retry + shutdown (depend on T011, T008)
```

**Phase 3 (US1)** — all tests in parallel first:
```
T012 [P]  T013 [P]  T014 [P]  T015 [P]   ← all failing tests committed
    ↓
T016 [P]  T017      T018      T019
```

**Phase 4 (US2)** — tests first, then parallel:
```
T020 [P]  T021 [P]              ← failing tests committed
    ↓
T022 [P]  T025 [P]              ← parallel (different files)
    ↓
T023                            ← sequential after T022 (same file)
    ↓
T024                            ← wiring (depends on T022, T023, T025)
```

---

## Implementation Strategy

### MVP (User Story 1 Only)

1. Complete Phase 1 (Setup)
2. Complete Phase 2 (Foundational) — blocks everything
3. Complete Phase 3 (US1 — batch processor) — **STOP AND VALIDATE**
4. Files processing correctly → MVP shippable

### Incremental Delivery

1. Phase 1 + 2 → Foundation ready
2. Phase 3 → Batch processing works (operators can check `processed/` folder)
3. Phase 4 → Live dashboard added (operators get real-time visibility)
4. Phase 5 → macOS daemon setup (operators get production-grade reliability)
5. Phase 6 → Quality gates pass, PR ready

---

## Notes

- `[P]` = different files, no blocking dependencies — safe to run in parallel
- `[US#]` = traces to specific user story for independent verification
- TDD order is non-negotiable (Constitution Principle II): failing test commit MUST predate implementation commit in git history
- Retire `scanner/watcher.py` in T010 — do not port its watchdog logic; only the HTTP upload logic migrates to `scanner/uploader.py`
- The `asyncio.Queue` in `AppState` (T025) bridges the sync batch runner thread and the async SSE endpoint — in `__main__.py`, capture `loop = asyncio.get_event_loop()` before starting uvicorn and store it on `AppState`; from the scheduler thread call `state.loop.call_soon_threadsafe(state.event_queue.put_nowait, event)` — do NOT use `asyncio.get_event_loop()` from a non-async thread (deprecated/broken in Python 3.12)
