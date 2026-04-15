# Research: PDF Scan Batch Processing

**Branch**: `003-we-watch-all` | **Date**: 2026-04-14

## Decision Log

---

### 1. PDF Processing Library

**Decision**: PyMuPDF (`pymupdf` / `import fitz`)

**Rationale**:
- Renders PDF pages directly to PIL/Pillow images with one call (`page.get_pixmap()`)
- Exposes `page.rotation` — the PDF rotation metadata flag written by most scanner software; applying this first is free and covers the majority of real-world cases
- Self-contained Python wheel; no external binaries or system packages required
- Excellent macOS (arm64 + x86_64) support via pre-built wheels
- Handles multi-page PDFs natively (`fitz.open(path)`, iterate `doc.pages()`)

**Alternatives Considered**:
- `pypdf`: Pure Python, lightweight, good for page count; cannot render pages to images — eliminated
- `pdf2image`: High-quality rendering but requires `poppler` installed via `brew`; external binary dependency adds installation complexity — rejected
- `pdfplumber`: Text/table extraction focus, not page rendering — not applicable

---

### 2. Orientation Detection Strategy

**Decision**: Two-tier approach — PDF rotation metadata first, pytesseract OSD fallback

**Rationale**:

**Tier 1 — PDF metadata rotation** (`page.rotation` via PyMuPDF):
- Most scanners (including ARIA) embed a rotation value in PDF page metadata
- PyMuPDF exposes this as an integer (0, 90, 180, 270)
- Correcting it is free: `page.set_rotation(0)` before rasterising
- Covers the majority of real-world "rotated page" cases with zero image analysis cost

**Tier 2 — Tesseract OSD fallback** (`pytesseract.image_to_osd()`):
- For pages where PDF metadata rotation is 0 but rendered content is visually rotated (rare but possible for certain scanners)
- Tesseract's Orientation and Script Detection (OSD) reports the detected text angle
- Applied only when Tier 1 yields rotation = 0 and the image appears non-upright
- Requires `brew install tesseract` on macOS — documented in quickstart.md

**Fallback behaviour (both tiers fail)**:
- Page uploaded as-is in best-guess orientation
- Flagged in dashboard and logs as `orientation_uncertain: true`
- Consistent with spec assumption: "uploaded in best-guess orientation and flagged in dashboard as needing manual review"

**Alternatives Considered**:
- OpenCV-based Hough transform for text-line detection: complex, high dependency weight — rejected
- Custom CNN orientation classifier: overkill for 4-class (0/90/180/270) problem — rejected
- Metadata-only (no fallback): misses scanners that do not write rotation metadata — rejected

---

### 3. Web Dashboard: Framework & Real-Time Push

**Decision**: FastAPI + uvicorn + Server-Sent Events (SSE)

**Rationale**:
- **FastAPI**: Async-native Python web framework; minimal boilerplate; automatic OpenAPI docs; type-safe request/response models
- **uvicorn**: ASGI server; runs FastAPI efficiently; supports graceful shutdown via SIGTERM — satisfies Constitution Principle I (lifecycle management)
- **SSE (Server-Sent Events)**: Browser-native one-way push (EventSource API); no library needed on the client side; ideal for progress streaming (unidirectional); far simpler than WebSocket for this use case
- Dashboard HTML is served as a single static file from FastAPI; no frontend build step required

**Real-time update architecture**:
- `BatchRunState` (shared in-memory, protected by `threading.Lock`) is updated by the batch runner thread
- SSE endpoint polls state every 1 second and yields JSON events to connected browsers
- Browser `EventSource` reconnects automatically on disconnect

**Alternatives Considered**:
- Flask + gevent SSE: requires gevent monkey-patching for async behaviour; heavier setup — rejected
- FastAPI + WebSocket: bidirectional overhead unnecessary for progress display — rejected
- Simple HTTP polling (no push): clients would need to refresh or poll; acceptable UX but inferior to SSE for minimal extra complexity — rejected

---

### 4. Scheduler: Embedded APScheduler vs External Cron

**Decision**: APScheduler (`BackgroundScheduler` with `ThreadPoolExecutor`) embedded in the FastAPI process

**Rationale**:
- Single process manages both web server and batch scheduling — one launchd plist, one log stream, one process to monitor
- `BackgroundScheduler` runs batch jobs in background threads; does not block uvicorn's event loop
- `ThreadPoolExecutor` allows concurrent batch runs (satisfying FR-015: parallel runs allowed)
- Interval configurable at startup from `settings.cron_interval_seconds`
- Eliminates the need for a separate launchd `StartCalendarInterval` entry

**Alternatives Considered**:
- `launchd StartCalendarInterval` (external cron): fires a new process every minute; requires separate launchd plist + shared state via file; dashboard process would need to poll a JSON file — rejected (higher complexity)
- `cron` (system crontab): deprecated for daemons on modern macOS; no sleep/wake awareness — rejected
- Celery: heavyweight task queue; requires Redis or RabbitMQ broker — overkill for this use case — rejected

---

### 5. macOS Service Management

**Decision**: launchd `LaunchAgent` with `KeepAlive: true`

**Rationale**:
- launchd is the macOS-native process supervisor; survives reboots automatically when plist is in `~/Library/LaunchAgents/`
- `KeepAlive: true` restarts the process if it crashes (equivalent to Docker `restart: unless-stopped`)
- Logs stdout/stderr to a configurable file path
- Does NOT require Docker Desktop running — eliminates a startup-order dependency with SMB mount
- The SMB share must be mounted before the daemon processes files; documented as a prerequisite in quickstart.md; `launchd` `WaitForPaths` key can be used to delay start until the volume is mounted

**`WaitForPaths` usage**: Add `/Volumes/aria/ARIAscans` to the plist's `WaitForPaths` array — launchd will not start the process until that path exists (i.e., the SMB share is mounted).

**Alternatives Considered**:
- Docker Desktop: works but requires Docker Desktop to be running and auto-started; SMB volume mapping on macOS is flaky across Docker Desktop versions — rejected
- `launchd StartCalendarInterval` (periodic, not persistent): process exits after each run; web server cannot be persistent — rejected
- `brew services`: wraps launchd under the hood; fine for development, but direct plist gives more control over `WaitForPaths` and env vars — noted as dev convenience option

---

### 6. Atomic File Claiming on SMB Volume

**Decision**: `Path.rename()` as primary; `shutil.move()` fallback on `OSError(errno.EXDEV)`

**Rationale**:
- `os.rename()` (called by `Path.rename()`) is atomic at the POSIX level for paths on the same filesystem/volume
- SMB protocol implements RENAME atomically within the same share — both `ARIAscans/` and `ARIAscans/in-progress/` are on the same SMB share, so cross-directory rename is safe
- If a future deployment uses different mounts (EXDEV error), fall back to `shutil.move()` (copy + delete); this is not atomic but is the only option in that case; log a WARNING
- Race condition window: two concurrent runs both attempt `rename()` on the same file; only one succeeds (the OS guarantees this); the loser gets `FileNotFoundError` — catch and skip gracefully

**Alternatives Considered**:
- File locking (`.lock` sentinel file): more complex, not OS-atomic — rejected
- Database-backed claim table: overkill, adds persistence dependency — rejected

---

### 7. Dependency Changes

| Package | Action | Reason |
|---------|--------|--------|
| `watchdog` | **Remove** | Replaced by APScheduler periodic scan |
| `pymupdf` | **Add** | PDF page rendering and rotation metadata |
| `Pillow` | **Add** | PIL image type used by PyMuPDF pixmap conversion |
| `pytesseract` | **Add** | OSD orientation fallback (requires `brew install tesseract`) |
| `fastapi` | **Add** | Web framework for dashboard |
| `uvicorn[standard]` | **Add** | ASGI server (includes `websockets` and `httptools` for performance) |
| `apscheduler` | **Add** | Embedded cron scheduler |
| `httpx` | **Add (test-only)** | Async HTTP client for FastAPI integration tests |
| `pytest-asyncio` | **Add (test-only)** | Async test support |
| `pytest-cov` | **Add (test-only)** | Coverage reporting |
| `requests` | **Keep** | Upload HTTP client |
| `pydantic-settings` | **Keep** | Config model |
| `python-dotenv` | **Keep** | `.env` loading |
