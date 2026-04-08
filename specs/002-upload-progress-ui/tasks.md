# Tasks: Upload Progress Dashboard

**Input**: Design documents from `specs/002-upload-progress-ui/`
**Branch**: `002-upload-progress-ui`
**Generated**: 2026-04-08

**TDD Note**: The project constitution (Principle II) mandates TDD without exception. All test tasks MUST be committed and confirmed failing before their paired implementation tasks begin.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no blocking dependency)
- **[Story]**: User story this task belongs to ([US1], [US2], [US3])

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Install new dependencies. No implementation may begin until this phase is complete.

- [ ] T001 Add `fastapi>=0.100.0`, `uvicorn[standard]>=0.24.0`, `sse-starlette>=2.1.0` to `requirements.txt`
- [ ] T002 [P] Add `pytest-asyncio>=0.23.0`, `httpx>=0.27.0` to `requirements-dev.txt`

**Checkpoint**: `pip install -r requirements.txt -r requirements-dev.txt` succeeds; `python -c "import fastapi, uvicorn, sse_starlette"` exits 0; `pytest` still collects existing 45 tests and passes.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Implement the `StatusStore` singleton and `dashboard_port` config field. All three user stories depend on these. No user story work may begin until this phase is complete.

⚠️ **CRITICAL**: Write tests first — confirm they FAIL — then implement.

- [ ] T003 Write failing unit tests for `StatusStore` in `tests/unit/test_store.py`: `Status` enum has `PENDING`, `UPLOADING`, `SUCCESS`, `FAILED` values that serialise as lowercase strings; `FileRecord` has all required fields (`id`, `filename`, `status`, `detected_at`, `updated_at`, `error_message`, `attempts`) and `to_json()` returns valid JSON including all fields; `StatusStore.add()` stores a `FileRecord` retrievable by `all()`; `StatusStore.update()` transitions `status` and refreshes `updated_at`; `StatusStore.all()` returns a thread-safe snapshot (not a reference); `subscribe()` returns an `asyncio.Queue` added to subscribers list; `unsubscribe()` removes it
- [ ] T004 [P] Write failing unit test for `dashboard_port` field in `tests/unit/test_config.py`: default value is `8080`; can be overridden via `DASHBOARD_PORT` env var (case-insensitive)
- [ ] T005 Implement `scanner/store.py`: `Status` enum with `PENDING`, `UPLOADING`, `SUCCESS`, `FAILED` (`.value` is lowercase string for JSON); `FileRecord` dataclass with fields `id: str`, `filename: str`, `status: Status`, `detected_at: datetime`, `updated_at: datetime`, `error_message: str | None`, `attempts: int`, and `to_json() -> str` method; `StatusStore` class with `_records: dict[str, FileRecord]`, `_lock: threading.Lock`, `_subscribers: list[asyncio.Queue[str]]`, `_loop: asyncio.AbstractEventLoop | None`, and methods `add()`, `update()`, `all()`, `subscribe()`, `unsubscribe()`, `set_loop()`, `_broadcast()`; module-level `status_store: StatusStore` singleton
- [ ] T006 [P] Update `scanner/config.py`: add `dashboard_port: int = 8080` field

**Checkpoint**: `pytest tests/unit/test_store.py tests/unit/test_config.py` — all tests pass; `mypy --strict scanner/store.py scanner/config.py` — zero errors.

---

## Phase 3: User Story 1 — Live Upload Dashboard (P1) 🎯 MVP

**Goal**: A browser opened at `http://localhost:{DASHBOARD_PORT}` shows all detected files and their upload status updating in real time via SSE within 1 second of each event.

**Independent Test**: Start scanner with mock HTTP backend; open `GET /api/events` SSE stream; drop a single image into watch dir; assert three SSE events arrive within 5 s (pending → uploading → success/failed); assert `GET /api/files` returns the file record; assert `GET /` returns 200 HTML.

> ⚠️ **Write ALL tests in this section first. Confirm each FAILS. Then implement.**

### Tests — User Story 1

- [ ] T007 [P] [US1] Write failing unit tests for FastAPI routes in `tests/unit/test_api.py`: `GET /` returns HTTP 200 with `Content-Type: text/html`; `GET /health` returns `{"status": "ok"}`; `GET /api/files` returns `[]` when `StatusStore` is empty; `GET /api/events` responds with `Content-Type: text/event-stream`; pre-existing records injected into store are included in `GET /api/files` response
- [ ] T008 [P] [US1] Write failing unit tests in `tests/unit/test_watcher.py` for watcher-store integration: `ImageEventHandler._handle()` calls `status_store.add()` with a `FileRecord(status=PENDING)` on file detection; queue now holds a `QueueItem(path, record_id)` named tuple; `process_file()` calls `status_store.update(record_id, status=UPLOADING)` before `upload_image()`; on `UploadResult(success=True)`, calls `status_store.update(record_id, status=SUCCESS)`; on `UploadResult(success=False)`, calls `status_store.update(record_id, status=FAILED, error_message=...)`
- [ ] T009 [P] [US1] Write failing integration test in `tests/integration/test_dashboard_integration.py`: start scanner (observer + worker thread) with `status_store` singleton and mock HTTP server; drop one image file; poll `status_store.all()` until the record's status reaches `SUCCESS` within 5 s; verify the record progressed through `PENDING → UPLOADING → SUCCESS`; assert file was moved to `processed/`

### Implementation — User Story 1

- [ ] T010 [US1] Implement `scanner/api.py`: `DASHBOARD_HTML: str` constant — complete single-page dashboard HTML with vanilla JS `EventSource` connecting to `/api/events`, auto-reconnect on close, table of file rows updated on each SSE event (filename, status badge, attempts, timestamp, error column); `app = FastAPI()`; `GET /` → `HTMLResponse(DASHBOARD_HTML)`; `GET /health` → `{"status": "ok"}`; `GET /api/files` → `[record.to_dict() for record in status_store.all()]`; `GET /api/events` → `EventSourceResponse` generator that calls `status_store.subscribe()`, yields events from the queue, and calls `status_store.unsubscribe()` on disconnect; `@app.on_event("startup")` sets `status_store.set_loop(asyncio.get_event_loop())`
- [ ] T011 [US1] Update `scanner/watcher.py`: add `QueueItem` dataclass (`path: Path`, `record_id: str`); update `ImageEventHandler._handle()` to generate `record_id = str(uuid.uuid4())`, call `status_store.add(FileRecord(id=record_id, filename=path.name, status=Status.PENDING, ...))`, and put `QueueItem(path, record_id)` into the queue; update `upload_queue` type annotation to `queue.Queue[QueueItem]`; update `process_file()` signature to accept `record_id: str` and call `status_store.update()` at uploading, success, and failed transitions; update `build_observer()` `_worker` to unpack `QueueItem`
- [ ] T012 [US1] Update `scanner/__main__.py`: import `uvicorn` and `scanner.api.app`; instantiate `uvicorn.Config(app, host="0.0.0.0", port=settings.dashboard_port, log_level="warning")` and `uvicorn.Server(config)`; start server in a `daemon=True` `threading.Thread` named `"api-server"` before observer starts; log `"Dashboard server started on port %d"` at INFO level; add `server.should_exit = True` before `observer.stop()` in shutdown sequence

**Checkpoint**: `pytest tests/unit/ tests/integration/test_dashboard_integration.py` — all green; `python -m scanner` starts without error; `GET http://localhost:8080/health` returns `{"status": "ok"}`; drop image in `incoming/` — dashboard at `http://localhost:8080` updates within 1 s.

---

## Phase 4: User Story 2 — Session Upload History (P2)

**Goal**: All uploads processed in the current session remain visible in the dashboard, including completed and failed files.

**Independent Test**: Upload 5 files successfully, then upload 2 more; `GET /api/files` returns all 7 records; none are purged after reaching `success` or `failed` status.

> ⚠️ **Write ALL tests first. Confirm each FAILS. Then implement.**

### Tests — User Story 2

- [ ] T013 [P] [US2] Write failing unit tests in `tests/unit/test_api.py` and `tests/unit/test_store.py` for session history: `StatusStore` with 3 records (1 pending, 1 success, 1 failed) — `all()` returns all 3; `GET /api/files` response includes all 3; `StatusStore.update()` to a terminal status does NOT remove the record; adding a new record after terminal records still returns all records via `all()`

### Implementation — User Story 2

- [ ] T014 [US2] Verify `StatusStore._records` has no eviction, TTL, or size-limit logic — records persist until process exit; confirm `GET /api/files` in `scanner/api.py` calls `status_store.all()` with no filtering predicate; run T013 tests — if all pass, no implementation change needed; if any fail, fix the offending logic in `scanner/store.py` or `scanner/api.py`

**Checkpoint**: `pytest tests/unit/test_store.py tests/unit/test_api.py` — all tests including T013 pass.

---

## Phase 5: User Story 3 — Failed Upload Visibility (P3)

**Goal**: Failed file rows are visually distinct in the dashboard and display the error reason.

**Independent Test**: Configure mock backend to return 401; drop a file; `GET /api/files` shows `"status": "failed"` with a non-null `"error_message"`; dashboard HTML renders failed rows with a different visual style (e.g., red colour or "Failed" badge).

> ⚠️ **Write ALL tests first. Confirm each FAILS. Then implement.**

### Tests — User Story 3

- [ ] T015 [P] [US3] Write failing unit tests in `tests/unit/test_store.py` and `tests/unit/test_api.py`: `FileRecord(status=FAILED, error_message="HTTP 401 — will not retry")` → `to_json()` includes `"error_message"` key with non-null value; `GET /api/files` response body for a failed record includes a non-null `"error_message"` field; `StatusStore.update(id, status=FAILED, error_message=None)` raises `ValueError` (error_message is required for FAILED)

### Implementation — User Story 3

- [ ] T016 [US3] Update `scanner/store.py`: in `StatusStore.update()` add guard — if `status == Status.FAILED` and `error_message` is `None`, raise `ValueError("error_message required for FAILED status")`; update `scanner/api.py` `DASHBOARD_HTML`: add CSS class `status-failed` (red background or border, "✗" icon) for rows with `status === "failed"`; add CSS class `status-success` (green) for `"success"` rows; render `error_message` in a dedicated column (show `—` for non-failed rows)

**Checkpoint**: `pytest tests/unit/ tests/integration/` — all green including failure-visibility tests.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Quality gates, documentation, and final validation per the project constitution.

- [ ] T017 Run `ruff check . && ruff format --check .` across the entire repo; fix all linting and formatting violations in `scanner/store.py`, `scanner/api.py`, and all new/modified test files (`tests/unit/test_store.py`, `tests/unit/test_api.py`, `tests/unit/test_config.py`, `tests/unit/test_watcher.py`, `tests/integration/test_dashboard_integration.py`)
- [ ] T018 Run `mypy --strict scanner/` and fix all type errors; ensure `store.py` is fully annotated (`asyncio.Queue[str]`, `asyncio.AbstractEventLoop | None`, `threading.Lock`, `dict[str, FileRecord]`); ensure `api.py` return types are correct (`HTMLResponse`, `dict[str, str]`, `list[dict[str, object]]`, `EventSourceResponse`); ensure `watcher.py` `QueueItem` and updated `process_file()` signature are fully typed
- [ ] T019 Run `pytest --cov=scanner --cov-report=term-missing`; verify coverage ≥ 90% on all scanner modules including `scanner/store.py` and `scanner/api.py`; add targeted unit tests for any uncovered branches (e.g., `_broadcast()` with no subscribers, `set_loop()` called twice, SSE disconnect path)
- [ ] T020 [P] Update `README.md`: add `DASHBOARD_PORT` row to the environment variables table; add an "Upload Progress Dashboard" section with the dashboard URL (`http://localhost:{DASHBOARD_PORT}`), Docker port mapping example (`"${DASHBOARD_PORT:-8080}:8080"` in `docker-compose.yml`), and `EXPOSE 8080` Dockerfile note
- [ ] T021 [P] Update `specs/002-upload-progress-ui/quickstart.md` if any commands, ports, or env vars changed during implementation; verify all commands in the quickstart are accurate against the final implementation
- [ ] T022 Perform final end-to-end smoke test per `specs/002-upload-progress-ui/quickstart.md`: `docker compose up --build`, open `http://localhost:8080`, confirm empty-state message appears; drop 3 test images; confirm all 3 appear in the dashboard with status transitions visible; confirm logs show `"Dashboard server started on port 8080"` and upload success lines

**Checkpoint**: All quality gates pass — `ruff check .` ✅, `mypy --strict scanner/` ✅, `pytest --cov=scanner` ✅ (≥90%), `README.md` updated ✅.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1 (Setup)**: No dependencies — start immediately
- **Phase 2 (Foundational)**: Depends on Phase 1 — blocks all user stories
- **Phase 3 (US1)**: Depends on Phase 2 — write tests first, confirm fail, then implement
- **Phase 4 (US2)**: Depends on Phase 2 — mostly a verification of Phase 2 correctness
- **Phase 5 (US3)**: Depends on Phase 3 — error_message display requires dashboard HTML from T010/T016
- **Phase 6 (Polish)**: Depends on Phases 3–5 complete

### Within Each User Story

1. Write all tests for the story → confirm each FAILS
2. Implement in order: data model → service integration → API/UI → lifecycle
3. Run tests → confirm all PASS
4. Commit with message: `test: [US?] <what the test verifies>` before `feat: [US?] <what was implemented>`

### Parallel Opportunities

- T001, T002 can run in parallel with each other (different files)
- T003, T004 can run in parallel (different test files)
- T005, T006 can run in parallel (different source files)
- T007, T008, T009 can all be written in parallel (different test files)
- T010, T011, T012 — T011 must precede T012 (watcher changes needed for __main__ to work); T010 is independent
- T013 can run in parallel with T015 (different test scenarios)
- T017, T018, T019 — run sequentially (fix lint before type check; fix type errors before measuring coverage)
- T020, T021 can run in parallel (different files)

---

## Parallel Example: User Story 1 Test Writing

```
Simultaneously write (different files, no conflicts):
  T007 → tests/unit/test_api.py         (API route tests)
  T008 → tests/unit/test_watcher.py     (store integration tests)
  T009 → tests/integration/test_dashboard_integration.py
```

---

## Implementation Strategy

### MVP (User Story 1 Only — P1)

1. Complete Phase 1: Setup
2. Complete Phase 2: Foundational — StatusStore + config field
3. Write T007, T008, T009 → confirm all FAIL
4. Complete T010–T012 → confirm all PASS
5. **STOP and VALIDATE**: `python -m scanner`, open `http://localhost:8080`, drop one image, confirm live status transitions
6. This alone satisfies FR-001 through FR-004, FR-007, FR-008, FR-009, FR-010

### Incremental Delivery

1. MVP: US1 → live dashboard with real-time SSE updates
2. Add US2 → history retained for session (minimal or no new code)
3. Add US3 → failed rows visually distinct with error detail
4. Polish → quality gates, README, smoke test

---

## Task Count Summary

| Phase | Tasks | Test Tasks | Impl Tasks |
|-------|-------|------------|------------|
| Phase 1: Setup | 2 | — | 2 |
| Phase 2: Foundational | 4 | 2 (T003, T004) | 2 (T005, T006) |
| Phase 3: US1 | 6 | 3 (T007–T009) | 3 (T010–T012) |
| Phase 4: US2 | 2 | 1 (T013) | 1 (T014) |
| Phase 5: US3 | 2 | 1 (T015) | 1 (T016) |
| Phase 6: Polish | 6 | 1 (T019) | 5 |
| **Total** | **22** | **8** | **14** |
