# Data Model: Upload Progress Dashboard

**Branch**: `002-upload-progress-ui` | **Date**: 2026-04-08

---

## Entities

### `Status` (Enum)

Represents the lifecycle stage of a single file upload attempt.

| Value | Description |
|-------|-------------|
| `pending` | File detected by watchdog; awaiting settle delay |
| `uploading` | HTTP POST in progress (first or retry attempt) |
| `success` | Backend returned 2xx; file moved to `processed/` |
| `failed` | All retry attempts exhausted or 4xx received; file left in watch root |

**Validation rules**:
- Only forward transitions are valid: `pending → uploading → success | failed`.
- A record already in `success` or `failed` is terminal — no further transitions.

---

### `FileRecord` (Dataclass)

Represents one file's upload lifecycle within a session.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `id` | `str` (UUID4) | Yes | Unique identifier per detection event; prevents collision on same filename |
| `filename` | `str` | Yes | Base name of the file (not full path) |
| `status` | `Status` | Yes | Current lifecycle stage |
| `detected_at` | `datetime` (UTC) | Yes | When the watchdog first saw the file |
| `updated_at` | `datetime` (UTC) | Yes | When the status last changed |
| `error_message` | `str \| None` | No | Populated only on `failed` status; includes HTTP status code or exception message |
| `attempts` | `int` | Yes | Number of upload attempts made; starts at 0, incremented on each try |

**Validation rules**:
- `id` must be a valid UUID4 string.
- `filename` must not be empty.
- `error_message` MUST be non-null when `status == failed`.
- `attempts` must be ≥ 0.

---

### `StatusStore` (Service / Singleton)

Thread-safe in-memory container shared between the scanner worker thread and the FastAPI event loop.

| Field | Type | Description |
|-------|------|-------------|
| `_records` | `dict[str, FileRecord]` | All `FileRecord` objects keyed by `id` |
| `_lock` | `threading.Lock` | Protects reads/writes to `_records` |
| `_subscribers` | `list[asyncio.Queue[str]]` | One queue per connected SSE client; holds JSON-serialised `FileRecord` payloads |
| `_loop` | `asyncio.AbstractEventLoop \| None` | Reference to the uvicorn event loop; set at server startup |

**Methods**:
- `add(record: FileRecord) → None` — add a new record; broadcasts SSE event.
- `update(id: str, *, status: Status, error_message: str | None = None, attempts: int | None = None) → None` — update an existing record; broadcasts SSE event.
- `all() → list[FileRecord]` — returns a snapshot of all records (thread-safe copy).
- `subscribe() → asyncio.Queue[str]` — called from the SSE endpoint to register a new subscriber queue.
- `unsubscribe(q: asyncio.Queue[str]) → None` — called on SSE client disconnect.
- `set_loop(loop: asyncio.AbstractEventLoop) → None` — called once at uvicorn startup.
- `_broadcast(payload: str) → None` — internal; pushes JSON payload to all subscriber queues via `asyncio.run_coroutine_threadsafe`.

---

## State Machine

```
                 ┌──────────┐
                 │  pending │  ← file detected by watchdog
                 └────┬─────┘
                      │ worker thread picks up file
                      ▼
                 ┌──────────┐
                 │uploading │  ← HTTP POST attempt(s) underway
                 └────┬─────┘
           ┌──────────┴──────────┐
           │ 2xx received        │ 4xx / all 5xx retries exhausted
           ▼                     ▼
      ┌─────────┐           ┌────────┐
      │ success │           │ failed │
      └─────────┘           └────────┘
       (terminal)            (terminal)
```

---

## SSE Event Payload

Each SSE event is a JSON object matching the `FileRecord` schema, serialised as a single-line string:

```json
{
  "id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
  "filename": "scan_001.jpg",
  "status": "success",
  "detected_at": "2026-04-08T10:23:45.123456Z",
  "updated_at": "2026-04-08T10:23:46.789012Z",
  "error_message": null,
  "attempts": 1
}
```

SSE wire format:
```
data: {"id": "...", "filename": "...", "status": "success", ...}\n\n
```

---

## Integration Points with Feature 001

| Feature 001 site | Change required |
|-----------------|-----------------|
| `scanner/watcher.py` — `ImageEventHandler._handle()` | Call `status_store.add(FileRecord(..., status=pending))` on file detection |
| `scanner/watcher.py` — `process_file()` | Call `status_store.update(id, status=uploading)` before `upload_image()`; call `status_store.update(id, status=success|failed, ...)` after |
| `scanner/__main__.py` | Start uvicorn server thread before watchdog observer; pass store reference |
| `scanner/config.py` | Add `dashboard_port: int = 8080` |
