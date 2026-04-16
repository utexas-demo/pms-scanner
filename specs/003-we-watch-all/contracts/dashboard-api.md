# Contract: Dashboard API

**Base URL**: `http://<mac-local-ip>:{DASHBOARD_PORT}` (default port: 8080)  
**Auth**: None — open on MedPath Wi-Fi  
**Provider**: `scanner/dashboard.py` (FastAPI + uvicorn)

---

## `GET /`

Returns the dashboard HTML page.

**Response**: `text/html` — single-page dashboard with auto-connecting `EventSource`

---

## `GET /status`

Returns a JSON snapshot of the current and last batch run. Safe to poll; also used by the dashboard HTML on initial load.

**Response** `200 application/json`:
```json
{
  "current_run": {
    "run_id": "550e8400-e29b-41d4-a716-446655440000",
    "started_at": "2026-04-14T19:35:00Z",
    "completed_at": null,
    "status": "running",
    "recovered_files": [],
    "files": [
      {
        "filename": "20260414192055.pdf",
        "total_pages": 33,
        "status": "in_progress",
        "started_at": "2026-04-14T19:35:01Z",
        "completed_at": null,
        "pages": [
          {
            "page_num": 7,
            "total_pages": 33,
            "rotation_applied": 90,
            "orientation_uncertain": false,
            "upload_success": true,
            "error": null
          }
        ]
      }
    ]
  },
  "last_run": { "...": "same shape, or null if first run" }
}
```

**`current_run`**: `null` if no run is currently active.  
**`last_run`**: `null` if no run has ever completed.

---

## `GET /events`

Server-Sent Events stream. The browser's `EventSource` connects here and receives push events as pages complete.

**Response**: `text/event-stream`

**Event types**:

| Event | When | Data |
|-------|------|------|
| `run_started` | New batch run begins | `{ "run_id": "...", "started_at": "..." }` |
| `file_started` | A file is claimed and processing begins | `{ "run_id": "...", "filename": "...", "total_pages": 33 }` |
| `page_done` | A single page upload completes (success or fail) | `{ "run_id": "...", "filename": "...", "page_num": 7, "total_pages": 33, "success": true, "rotation_applied": 90 }` |
| `file_done` | All pages of a file are complete | `{ "run_id": "...", "filename": "...", "status": "completed", "pages_succeeded": 33, "pages_failed": 0 }` |
| `run_done` | Batch run finishes | `{ "run_id": "...", "files_processed": 2, "total_pages": 45, "completed_at": "..." }` |
| `heartbeat` | Every 15 s if no other events | `{}` — keeps the connection alive through proxies |

**SSE wire format** (standard):
```
event: page_done
data: {"run_id": "...", "filename": "20260414192055.pdf", "page_num": 7, "total_pages": 33, "success": true, "rotation_applied": 90}

```

---

## `POST /run`

Manually triggers a batch run immediately, outside the scheduler. Useful for testing and for operators who want to process files without waiting for the next scheduled tick.

**Request body**: empty  
**Response** `202 application/json`:
```json
{ "run_id": "...", "message": "Batch run queued" }
```

**Response** `409 application/json` (if a run is already active on the same thread):
```json
{ "detail": "A batch run is already in progress" }
```

Note: Because parallel runs are allowed (FR-015), a 409 is only returned when the scheduler's thread pool is at capacity (all worker threads busy). In practice with the default pool size this will rarely occur.
