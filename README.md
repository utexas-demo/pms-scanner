# pms-scanner

Unattended image-upload service for Windows. Watches a local folder for new image files and POSTs each one to a configured backend endpoint using Bearer authentication.

## How it works

1. The service watches `WATCH_DIR` for new image files (`.jpg`, `.jpeg`, `.png`, `.gif`, `.bmp`, `.tiff`, `.webp`).
2. When a file is detected, the service waits `FILE_SETTLE_SECONDS` (default 0.5 s) to ensure the file is fully written.
3. The file is uploaded to `BACKEND_UPLOAD_URL` with a `Bearer` token from `API_TOKEN`.
4. **Success** → file is moved to `WATCH_DIR/processed/` for audit and to prevent re-upload on restart.
5. **Failure** → file remains in `WATCH_DIR` and is automatically retried the next time the service starts.

Failed uploads are retried up to 3 times per run with exponential back-off before being left in place.

---

## Quickstart (Docker — recommended)

```bash
# 1. Copy and fill in your environment
cp .env.example .env
#    Set BACKEND_UPLOAD_URL and API_TOKEN at minimum

# 2. Create the incoming folder (mapped as a Docker volume)
mkdir incoming

# 3. Build and start
docker compose up --build -d

# 4. Drop a test image
copy test.jpg incoming\

# Check logs
docker compose logs -f pms-scanner
```

---

## Quickstart (Python native)

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
pip install -r requirements.txt

cp .env.example .env
# Edit .env — set WATCH_DIR, BACKEND_UPLOAD_URL, API_TOKEN

python -m scanner
```

---

## Environment Variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `BACKEND_UPLOAD_URL` | **Yes** | — | Full URL of the backend upload endpoint |
| `API_TOKEN` | **Yes** | — | Bearer token for backend authentication |
| `WATCH_DIR` | No | `/data/incoming` | Absolute path to the folder to monitor |
| `WATCH_RECURSIVE` | No | `true` | Also monitor subdirectories |
| `FILE_SETTLE_SECONDS` | No | `0.5` | Delay after detection before upload (seconds) |
| `UPLOAD_TIMEOUT_SECONDS` | No | `30` | HTTP request timeout per attempt (seconds) |
| `LOG_LEVEL` | No | `INFO` | Log verbosity: `DEBUG` \| `INFO` \| `WARNING` \| `ERROR` |
| `DASHBOARD_PORT` | No | `8080` | Port for the upload progress dashboard HTTP server |

> **Security**: `API_TOKEN` is transmitted only in the `Authorization: Bearer` header. It is never stored in source code, Docker image layers, or log output (logs show only the first 4 characters).

---

## Docker volume mapping

The Docker Compose file maps the host `./incoming` folder to `/data/incoming` inside the container:

```yaml
volumes:
  - ./incoming:/data/incoming
```

To watch a different host folder (e.g. a network share or a specific Windows path), update the left side of the volume mapping in `docker-compose.yml`:

```yaml
volumes:
  - "C:/Users/ammar.darkazanli/Documents/Data/TIF Documents:/data/incoming"
```

Or set `WATCH_DIR` as an environment variable when running natively (without Docker).

---

## Upload Progress Dashboard

The service includes a real-time browser dashboard that shows upload status for all files detected in the current session.

**URL**: `http://localhost:{DASHBOARD_PORT}` (default `http://localhost:8080`)

The dashboard updates automatically via Server-Sent Events — no manual refresh needed. Each file shows its status (`pending` → `uploading` → `success` / `failed`), number of attempts, and error details for failures.

### Docker port mapping

Add to `docker-compose.yml` under the `pms-scanner` service:

```yaml
ports:
  - "${DASHBOARD_PORT:-8080}:8080"
```

And in `Dockerfile`:

```dockerfile
EXPOSE 8080
```

### API endpoints

| Endpoint | Description |
|----------|-------------|
| `GET /` | Dashboard HTML page |
| `GET /health` | Readiness probe — returns `{"status": "ok"}` |
| `GET /api/files` | JSON snapshot of all tracked files |
| `GET /api/events` | SSE stream of real-time status updates |

---

## File disposition

| Outcome | What happens to the file |
|---|---|
| Upload succeeds | Moved to `WATCH_DIR/processed/` |
| Upload fails (all retries) | Left in `WATCH_DIR` — retried on next service restart |

The `processed/` folder is created automatically. Files inside it are excluded from monitoring (they will not be re-uploaded).

---

## Development

```bash
# Install dev dependencies
pip install -r requirements.txt -r requirements-dev.txt

# Run tests
pytest

# With coverage
pytest --cov=scanner --cov-report=term-missing

# Lint + format check
ruff check .
ruff format --check .

# Type check
mypy --strict scanner/
```

All gates must pass before merging to `main`.

---

## Supported image formats

`.jpg` · `.jpeg` · `.png` · `.gif` · `.bmp` · `.tiff` · `.webp`
