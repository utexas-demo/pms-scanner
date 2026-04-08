# Data Model: Folder Monitor and File Upload

**Branch**: `001-folder-monitor-upload` | **Phase**: 1 | **Date**: 2026-04-08

## Entities

### WatchedFolder

Represents the local directory being monitored by the service.

| Field | Type | Description | Constraints |
|-------|------|-------------|-------------|
| `path` | `Path` | Absolute path to the watched directory | Must exist or be creatable at startup |
| `recursive` | `bool` | Whether subdirectories are also watched | Default: `true` |
| `settle_seconds` | `float` | How long to wait after detection before reading | Must be ≥ 0; spec requires exactly 0.5s |

**Source**: `Settings.watch_dir`, `Settings.watch_recursive`, `Settings.file_settle_seconds`

---

### DetectedFile

A file found in the watched folder that has been queued for upload.

| Field | Type | Description | Constraints |
|-------|------|-------------|-------------|
| `path` | `Path` | Absolute path to the file | Must exist and be readable |
| `name` | `str` | Filename (basename only) | Used in log messages and upload payload |
| `mime_type` | `str` | MIME type guessed from extension | Falls back to `application/octet-stream` |
| `detected_at` | `datetime` | UTC timestamp when detection event fired | Used for deduplication window |

**Supported image extensions**: `.jpg`, `.jpeg`, `.png`, `.gif`, `.bmp`, `.tiff`, `.webp`

**State machine**:
```
DETECTED → QUEUED → UPLOADING → UPLOADED → MOVED_TO_PROCESSED (file relocated to processed/)
                              → FAILED   → STAYS_IN_WATCH_ROOT (re-attempted on next restart)
```

---

### UploadRequest

The outbound HTTP request sent to the backend for a single file.

| Field | Type | Description | Constraints |
|-------|------|-------------|-------------|
| `endpoint_url` | `str` | Backend upload URL | From `Settings.backend_upload_url` |
| `file` | `DetectedFile` | The file to upload | Must be in DETECTED or QUEUED state |
| `auth_token` | `str` | Bearer token for authentication | From `Settings.api_token`; never logged in full |
| `folder` | `str` | Relative folder path within watch dir | Derived: `file.path.parent` relative to `watch_dir` |
| `timeout_seconds` | `int` | HTTP request timeout | Default: 30s |

**HTTP shape**:
- Method: `POST`
- Content-Type: `multipart/form-data`
- Headers: `Authorization: Bearer {auth_token}`
- Body parts: `file` = (filename, binary, MIME type); `folder` = relative path string

---

### UploadCredentials

Holds the authentication values used to authorise upload requests. Temporarily hard-coded via configuration; will be replaced by API login when that feature is implemented.

| Field | Type | Description | Constraints |
|-------|------|-------------|-------------|
| `api_token` | `str` | Bearer token issued by the backend | Supplied via `API_TOKEN` env var; never stored in source or logs |

---

### UploadResult

The outcome of a single upload attempt (or all retry attempts for a given file).

| Field | Type | Description | Constraints |
|-------|------|-------------|-------------|
| `file_path` | `Path` | Original path of the file (in watch root) | |
| `success` | `bool` | Whether the upload ultimately succeeded | |
| `http_status` | `int \| None` | HTTP status code from last attempt | `None` on network/timeout errors |
| `error_message` | `str \| None` | Human-readable error detail | `None` on success |
| `attempts` | `int` | Total number of attempts made | 1–3 per retry config |
| `completed_at` | `datetime` | UTC timestamp of final outcome | |
| `destination_path` | `Path \| None` | Path after move (inside `processed/`) | Set on success; `None` on failure |

---

## Relationships

```
WatchedFolder  ──(monitors)──►  DetectedFile  ──(produces)──►  UploadRequest
                                                                     │
                                                        UploadCredentials (injected)
                                                                     │
                                                                     ▼
                                                              UploadResult
```

---

## Validation Rules

- A `DetectedFile` MUST NOT be queued if its extension is not in `SUPPORTED_EXTENSIONS`.
- A `DetectedFile` MUST NOT be re-queued within 2 seconds of its last detection (deduplication window).
- An `UploadRequest` MUST NOT be submitted if `file.path` no longer exists at the moment of upload (file deleted between detection and upload).
- An `UploadResult` with `success=False` MUST include a non-null `error_message`.
- An `UploadResult` with `success=True` MUST include a non-null `destination_path` pointing to the file's new location inside `processed/`.
- `UploadCredentials.api_token` MUST be supplied at startup; service MUST fail fast with a clear error if absent.
- The `processed/` subfolder MUST be created automatically if absent before the first move; files inside it MUST NOT trigger upload events (excluded from watchdog scope or filtered by path).
- The watched folder (and its `processed/` child) MUST be created at startup if either does not exist.
