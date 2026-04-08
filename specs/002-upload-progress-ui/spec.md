# Feature Specification: Upload Progress Dashboard

**Feature Branch**: `002-upload-progress-ui`
**Created**: 2026-04-08
**Status**: Draft
**Input**: User description: "setup a browser with a fast API that allows the user to view the progress showing all the files with a progress bar as they are getting uploaded."

---

## User Scenarios & Testing *(mandatory)*

### User Story 1 — Live Upload Dashboard (Priority: P1)

A user opens a browser and sees a real-time dashboard listing every file the scanner has detected. Each file shows its current status and an upload progress indicator. The view updates automatically — no manual refresh needed.

**Why this priority**: This is the core deliverable. Without live status visibility there is no feature.

**Independent Test**: Start the scanner with a mock backend, drop 3 image files, open the dashboard URL — all 3 files appear with status transitions (pending → uploading → success) visible within 5 seconds without refreshing the page.

**Acceptance Scenarios**:

1. **Given** the scanner is running and the dashboard is open, **When** a new image file is dropped in the watch folder, **Then** the file appears in the dashboard within 1 second showing status `pending`.
2. **Given** a file is uploading, **When** the upload completes successfully, **Then** its row updates to `success` and the progress bar reaches 100%.
3. **Given** a file is uploading, **When** the backend returns an error after all retries, **Then** its row updates to `failed` and the error reason is shown.
4. **Given** the dashboard is open, **When** no files are being processed, **Then** an empty-state message is shown (e.g., "No files in queue.").

---

### User Story 2 — Session Upload History (Priority: P2)

The dashboard retains the full list of uploads for the current service run — including completed and failed files — so the user can audit what has been processed since the scanner started.

**Why this priority**: Without history the user loses context on completed uploads the moment a new file arrives.

**Independent Test**: Drop and successfully upload 5 files, then drop 2 more — the dashboard shows all 7 entries (5 success, 2 new), not just the 2 active ones.

**Acceptance Scenarios**:

1. **Given** 5 files have been successfully uploaded in this session, **When** the user opens or refreshes the dashboard, **Then** all 5 completed entries are still visible.
2. **Given** a failed upload is in the list, **When** the scanner retries on restart (new session), **Then** the history resets to an empty list (history is per-session, not persistent).

---

### User Story 3 — Failed Upload Visibility (Priority: P3)

Failed uploads are prominently distinguished from successful ones, and the error reason is shown so the user understands why the upload did not complete.

**Why this priority**: Without failure detail the user cannot diagnose problems.

**Independent Test**: Configure the backend to return 401; drop a file; confirm the dashboard row shows `failed` status and the error text contains the HTTP status code.

**Acceptance Scenarios**:

1. **Given** a file failed after all retries, **When** the user views the dashboard, **Then** the row is visually distinct (e.g., different colour or icon) from succeeded rows.
2. **Given** a file failed with HTTP 503, **When** the user reads the error field, **Then** it shows a human-readable message including the status code.

---

### Edge Cases

- What happens if the browser opens before the scanner has detected any files? → Empty-state message is shown.
- What happens if the SSE connection drops? → The browser automatically reconnects (standard `EventSource` reconnect behaviour).
- What happens when the scanner service stops while the dashboard is open? → SSE connection closes; the browser shows a reconnecting state; history already rendered remains visible.
- What happens if two files with the same name arrive at different times? → Each is tracked independently by a unique ID (not just filename).

---

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST expose a browser-accessible dashboard at a configurable URL (default `http://localhost:8080`).
- **FR-002**: Dashboard MUST display each tracked file as a row containing: filename, current status, progress indicator, and timestamp of last status change.
- **FR-003**: Dashboard MUST update in real time using Server-Sent Events (SSE) — status changes MUST appear within 1 second without a page reload.
- **FR-004**: System MUST track four file statuses: `pending` (detected, awaiting upload), `uploading` (upload in progress), `success` (upload confirmed), `failed` (all retries exhausted).
- **FR-005**: System MUST retain all upload events for the lifetime of the current scanner process (in-memory; no database required for v1).
- **FR-006**: Dashboard MUST display the error reason for any file in `failed` status.
- **FR-007**: System MUST expose a `/health` endpoint returning HTTP 200 for container readiness probes.
- **FR-008**: The scanner worker MUST publish status-change events to the shared state store so the API reflects live upload activity.
- **FR-009**: Dashboard MUST be served as a static HTML page by the FastAPI application — no separate frontend build step required.
- **FR-010**: System MUST allow the dashboard HTTP port to be configured via environment variable `DASHBOARD_PORT` (default `8080`).

### Key Entities

- **FileRecord**: Represents one file's upload lifecycle — `id` (unique UUID per detection), `filename`, `status` (pending / uploading / success / failed), `detected_at` (timestamp), `updated_at` (timestamp), `error_message` (nullable string).
- **StatusStore**: In-memory container shared between the scanner worker thread and the FastAPI app — holds all `FileRecord` objects for the current session; thread-safe.
- **SSE Event**: Payload pushed to connected browsers whenever a `FileRecord` status changes — contains the serialised `FileRecord`.

---

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: The dashboard page fully loads within 2 seconds on a local network connection.
- **SC-002**: Any status change (detection, upload start, completion, failure) is reflected in the browser within 1 second.
- **SC-003**: The dashboard correctly shows all files processed in the current session without omission after any number of uploads.
- **SC-004**: A user can identify at a glance which files are pending, uploading, completed, or failed with no ambiguity.
- **SC-005**: The service starts without requiring any additional installation steps beyond those already in `requirements.txt` (i.e., `fastapi` and an ASGI server are new dependencies but the user runs one command).

---

## Assumptions

- The dashboard is accessed locally or on a trusted LAN — no user authentication on the dashboard UI is required for v1.
- The FastAPI server runs in the same process as the scanner (same Python process, separate thread) — no additional service or port-forwarding setup required.
- History is in-memory and resets on service restart; persistent storage across restarts is out of scope for v1.
- Mobile-responsive layout is not required; the dashboard is expected to be viewed on a desktop browser.
- `fastapi`, `uvicorn` (or equivalent ASGI server), and `sse-starlette` (or equivalent SSE library) will be added to `requirements.txt`.
- Progress bars represent upload state transitions rather than byte-level transfer progress (the backend upload is a single multipart POST with no chunked progress events).
