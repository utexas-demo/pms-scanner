# Quickstart: Upload Progress Dashboard

**Feature**: `002-upload-progress-ui` | **Branch**: `002-upload-progress-ui`

---

## Prerequisites

Complete all steps from `specs/001-folder-monitor-upload/quickstart.md` first. Feature 002 builds on top of the running scanner service.

---

## Environment Variables (new in this feature)

| Variable | Required | Default | Description |
|---|---|---|---|
| `DASHBOARD_PORT` | No | `8080` | Port the progress dashboard HTTP server listens on |

All Feature 001 variables (`BACKEND_UPLOAD_URL`, `API_TOKEN`, `WATCH_DIR`, etc.) still apply.

---

## Running with Docker (recommended)

```bash
# Same docker-compose.yml — DASHBOARD_PORT is passed through automatically
docker compose up --build -d

# Open the dashboard
start http://localhost:8080
```

The `docker-compose.yml` should expose port `8080` (see volume/port mapping notes below).

---

## Running natively (Python)

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env
# Edit .env — DASHBOARD_PORT defaults to 8080 if not set

python -m scanner
# Dashboard available at http://localhost:8080
```

---

## Verifying the dashboard

1. Open `http://localhost:8080` in a browser.
2. You should see the empty-state message: "No files in queue."
3. Drop an image into the watch folder:
   ```bash
   copy test.jpg incoming\
   ```
4. The dashboard should update within 1 second showing `pending → uploading → success`.

---

## Running tests

```bash
# Install dev dependencies
pip install -r requirements.txt -r requirements-dev.txt

# Run all tests
pytest

# With coverage
pytest --cov=scanner --cov-report=term-missing

# Lint and format check
ruff check .
ruff format --check .

# Type check
mypy --strict scanner/
```

---

## Docker port mapping

Add to `docker-compose.yml` under the `pms-scanner` service:

```yaml
ports:
  - "${DASHBOARD_PORT:-8080}:8080"
```

And expose the port in `Dockerfile`:

```dockerfile
EXPOSE 8080
```

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---------|-------------|-----|
| Dashboard shows blank page / connection refused | `DASHBOARD_PORT` mismatch or port not exposed in Docker | Check `DASHBOARD_PORT` env var and `docker-compose.yml` port mapping |
| Status stuck on `uploading` | Backend unreachable; retries in progress | Check `BACKEND_UPLOAD_URL` and backend logs |
| SSE events not updating | Browser `EventSource` blocked by proxy | Ensure no HTTP proxy between browser and dashboard |
| `ImportError: sse_starlette` | Dependencies not installed | Run `pip install -r requirements.txt` again |
