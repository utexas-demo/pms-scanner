# Data Model: PDF Scan Batch Processing

**Branch**: `003-we-watch-all` | **Date**: 2026-04-14

## In-Memory State (module: `scanner/state.py`)

All state is held in memory within the running process. There is no database. State is reset when the process restarts (launchd KeepAlive will restart it; crash recovery is handled at the filesystem level via folder structure).

---

### `PageResult`

Represents the processing outcome of a single PDF page.

| Field | Type | Description |
|-------|------|-------------|
| `page_num` | `int` | 1-indexed page number within the source PDF |
| `total_pages` | `int` | Total pages in the source PDF (for display as "X/Y") |
| `rotation_applied` | `int` | Degrees rotated (0, 90, 180, 270); 0 means no correction needed |
| `orientation_uncertain` | `bool` | True if neither metadata nor OSD could determine orientation confidently |
| `upload_success` | `bool` | True if backend returned HTTP 2xx and page was accepted |
| `error` | `Optional[str]` | Error message if upload failed; None on success |

---

### `FileResult`

Represents the processing outcome of a single PDF file across all its pages.

| Field | Type | Description |
|-------|------|-------------|
| `filename` | `str` | Bare filename (e.g., `20260414192055.pdf`) |
| `total_pages` | `int` | Total page count determined before processing begins |
| `pages` | `list[PageResult]` | Results for each page, populated as uploads complete |
| `status` | `Literal["pending", "in_progress", "completed", "failed"]` | Current processing state |
| `started_at` | `datetime` | When this file's processing began (UTC) |
| `completed_at` | `Optional[datetime]` | When all pages finished (success or failure); None if still running |

**State transitions**:
```
pending → in_progress → completed
                      ↘ failed
```
- `failed`: any page upload fails and the file cannot continue (e.g., PDF unreadable)
- `completed`: all pages processed (individual page failures are logged but file is still `completed`)

---

### `BatchRunState`

Represents a single scheduled batch run.

| Field | Type | Description |
|-------|------|-------------|
| `run_id` | `str` | UUID4 string, unique per run |
| `started_at` | `datetime` | Run start timestamp (UTC) |
| `completed_at` | `Optional[datetime]` | Run end timestamp; None if still running |
| `files` | `list[FileResult]` | All files processed in this run (empty if no PDFs found) |
| `status` | `Literal["running", "completed", "failed"]` | Overall run status |
| `recovered_files` | `list[str]` | Filenames returned from `in-progress/` during crash recovery at run start |

---

### `AppState`

Top-level singleton held in `scanner/state.py`, shared between the batch runner and the dashboard.

| Field | Type | Description |
|-------|------|-------------|
| `current_run` | `Optional[BatchRunState]` | The currently executing run; None between runs |
| `last_run` | `Optional[BatchRunState]` | The most recently completed run; used by dashboard summary |
| `_lock` | `threading.Lock` | Protects all mutations; acquired before reading or writing any field |

**Access pattern**: Batch runner acquires lock, updates `current_run`, releases. SSE endpoint acquires lock, reads snapshot, releases. Lock is never held across a network call.

---

## Filesystem Layout

```text
/Volumes/aria/ARIAscans/          ← WATCH_DIR (configured via env var)
├── *.pdf                          ← new files dropped by scanner
├── in-progress/
│   └── *.pdf                      ← atomically claimed by a batch run (FR-013)
│                                  ← crash recovery: returned to root on next run start (FR-016)
└── processed/
    └── *.pdf                      ← successfully completed files (FR-014)
```

**Folder creation**: All three folders (`ARIAscans/`, `in-progress/`, `processed/`) are created with `mkdir(exist_ok=True)` at process startup if they do not already exist.

---

## Config Settings (additions to `scanner/config.py`)

New fields added to the `Settings(BaseSettings)` model:

| Field | Type | Default | Env Var | Description |
|-------|------|---------|---------|-------------|
| `cron_interval_seconds` | `int` | `60` | `CRON_INTERVAL_SECONDS` | How often the batch runner fires |
| `dashboard_port` | `int` | `8080` | `DASHBOARD_PORT` | Port the web dashboard listens on |
| `file_settle_seconds` | `float` | `10.0` | `FILE_SETTLE_SECONDS` | Existing field; default raised from 0.5 → 10.0 |

**Derived paths** (not config fields — computed at runtime from `watch_dir`):

```python
@property
def inprogress_dir(self) -> Path:
    return Path(self.watch_dir) / "in-progress"

@property
def processed_dir(self) -> Path:
    return Path(self.watch_dir) / "processed"
```
