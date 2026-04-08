# Contract: Dashboard API

**Feature**: `002-upload-progress-ui`
**Version**: 1.0.0
**Date**: 2026-04-08

This contract defines the HTTP interface exposed by the pms-scanner FastAPI server for the upload progress dashboard.

---

## Base URL

```
http://localhost:{DASHBOARD_PORT}
```

Default port: `8080` (configurable via `DASHBOARD_PORT` env var).

---

## Endpoints

### `GET /`

Returns the dashboard HTML page.

**Request**: No parameters, no body.

**Response**:
- `200 OK`
- `Content-Type: text/html; charset=utf-8`
- Body: complete HTML page with embedded JavaScript that opens an SSE connection to `/api/events`.

---

### `GET /health`

Readiness/liveness probe for Docker and process supervisors.

**Request**: No parameters, no body.

**Response**:
```json
HTTP/1.1 200 OK
Content-Type: application/json

{"status": "ok"}
```

---

### `GET /api/files`

Returns a JSON snapshot of all `FileRecord` objects tracked in the current session.

**Request**: No parameters, no body.

**Response**:
```json
HTTP/1.1 200 OK
Content-Type: application/json

[
  {
    "id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
    "filename": "scan_001.jpg",
    "status": "success",
    "detected_at": "2026-04-08T10:23:45.123456Z",
    "updated_at": "2026-04-08T10:23:46.789012Z",
    "error_message": null,
    "attempts": 1
  }
]
```

**Field rules**:
- `id`: UUID4 string; unique per detection event.
- `filename`: base filename only (no path).
- `status`: one of `"pending"`, `"uploading"`, `"success"`, `"failed"`.
- `detected_at` / `updated_at`: ISO 8601 UTC datetime with microsecond precision.
- `error_message`: `null` for non-failed records; non-null string for `"failed"` records.
- `attempts`: integer ≥ 0.

---

### `GET /api/events`

Server-Sent Events stream. Each event carries the full serialised `FileRecord` JSON when a status change occurs.

**Request**: No parameters. Client MUST set `Accept: text/event-stream`.

**Response**:
```
HTTP/1.1 200 OK
Content-Type: text/event-stream
Cache-Control: no-cache
Connection: keep-alive

data: {"id": "...", "filename": "scan_001.jpg", "status": "pending", ...}

data: {"id": "...", "filename": "scan_001.jpg", "status": "uploading", ...}

data: {"id": "...", "filename": "scan_001.jpg", "status": "success", ...}
```

**Event rules**:
- One event per status change (not per second).
- Each `data:` line is a complete JSON object (single line, no embedded newlines).
- Events are separated by double newline (`\n\n`).
- Heartbeat comments (`:\n\n`) are sent every 15 seconds to keep the connection alive through proxies.
- On client disconnect, the server removes the client's queue silently.

**Client reconnection**: Browsers using the native `EventSource` API will automatically reconnect on disconnect after ~3 seconds. No `id:` or `retry:` fields are sent by default (state is bootstrapped via `/api/files` on reconnect).

---

## Error Responses

| Scenario | HTTP Status | Body |
|----------|-------------|------|
| Internal server error | `500 Internal Server Error` | `{"detail": "<error message>"}` |
| Unknown route | `404 Not Found` | `{"detail": "Not Found"}` |

---

## CORS

No CORS headers are set. The dashboard is served from the same origin as the API endpoints. Cross-origin access is not required for v1.

---

## Security

- No authentication on the dashboard or API — intended for local / trusted LAN access only.
- No sensitive data (API tokens, file contents) is returned by any endpoint.
- `DASHBOARD_PORT` should not be exposed to the public internet.
