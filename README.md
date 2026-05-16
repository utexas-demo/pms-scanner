# pms-scanner

Cross-platform service that watches per-environment folders for PDF/TIFF
scans, orients every page, and uploads each page to the correct backend —
**production** scans to `adg.mpsinc.io`, **staging** scans to
`dev.adg.mpsinc.io` — with per-environment credentials. Designed to run
as a small fleet (`macmini`, `nuc`, …) sharing the same network-mounted
watch folders without a central coordinator.

## What it does

- **Routes by folder, not by flag**: a file's environment is decided
  solely by which watch folder it landed in (FR-002/003). No setting to
  flip; cross-contamination is structurally impossible.
- **Dual-environment, concurrent**: production and staging poll on
  independent staggered schedules and run in parallel.
- **Fleet-safe**: each machine self-identifies and claims files by
  atomic rename into its own `in-progress/<machine>/` subfolder; crash
  recovery is strictly per-machine.
- **NTP-gated**: refuses to start until its clock is verified against an
  NTP source, then re-checks drift hourly so the fleet stride holds.
- **Per-page processing**: PyMuPDF metadata + Tesseract OSD orientation
  correction, retry on transient upload failure.
- **Per-machine dashboard**: a two-pane (production/staging) live view
  with an NTP status banner and per-environment + machine-tagged events.

## Supported platforms

| OS | Min version | Supervisor |
|---|---|---|
| macOS | 13 (Ventura)+, Apple Silicon or Intel | launchd `LaunchAgent` ([docs/launchd-setup.md](docs/launchd-setup.md)) |
| Linux | Debian 12+ / Ubuntu 22.04+, x86_64 | `systemd --user` ([docs/systemd-setup.md](docs/systemd-setup.md)) |

The Python code is platform-agnostic; only the supervisor unit and the
optional clock-correction helper are OS-specific (Constitution v3.0.0,
Principle I — Cross-Platform Unattended Operation).

## Quick start

Full operator walkthrough for a two-machine fleet:
[`specs/004-multi-env-uploads/quickstart.md`](specs/004-multi-env-uploads/quickstart.md).

```bash
git clone https://github.com/mpsinc/pms-scanner.git && cd pms-scanner
python3.12 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env          # fill in MACHINE_IDENTITY, both env blocks, NTP
.venv/bin/python -m scanner   # foreground smoke test
```

Then install as a service via the platform guide above. Open
`http://<machine-ip>:8080` for the dashboard.

## Configuration

Loaded from environment variables (with `.env` support), nested via the
`__` separator. Source of truth:
[`specs/004-multi-env-uploads/contracts/config-schema.md`](specs/004-multi-env-uploads/contracts/config-schema.md).
The startup gate refuses to start (single ERROR line naming the
offending field) on any violation.

### Identity & NTP

| Variable | Default | Description |
|---|---|---|
| `MACHINE_IDENTITY` | *(required)* | This host's name; `^[a-z0-9][a-z0-9_-]{0,30}$`, not a reserved name |
| `ENVIRONMENTS` | *(required)* | Comma-separated enabled envs: `production,staging` |
| `NTP__SOURCE` | `pool.ntp.org` | NTP server for the offset check |
| `NTP__MAX_DRIFT_SECONDS` | `1.0` | Max tolerated offset before refuse-to-start / correction |
| `NTP__CHECK_INTERVAL_SECONDS` | `3600` | Recurring drift-check interval |
| `NTP__CORRECT_CLOCK_COMMAND` | `/usr/local/libexec/pms-scanner-correct-clock` | Privileged helper; blank = verify-only |
| `NTP__STARTUP_REQUIRED` | `true` | `false` (dev only) skips the gate with a WARNING |
| `NTP__STARTUP_TIMEOUT_SECONDS` | `30` | Gate timeout before refusing to start |

### Per-environment block (`<NAME>` = `PRODUCTION` or `STAGING`)

| Variable | Default | Description |
|---|---|---|
| `ENV_<NAME>__ENABLED` | `true` | Disable to run a single environment |
| `ENV_<NAME>__WATCH_DIR` | *(required)* | Watch folder; must be distinct per env (FR-009) |
| `ENV_<NAME>__BACKEND_BASE_URL` | prod `https://adg.mpsinc.io` / staging `https://dev.adg.mpsinc.io` | Upload target (https) |
| `ENV_<NAME>__API_TOKEN` | *(required)* | Bearer token; redacted in every log line |
| `ENV_<NAME>__REQUISITION_ID` | *(none)* | Optional UUID linked to every uploaded page |
| `ENV_<NAME>__SCHEDULE_OFFSET_SECONDS` | *(required)* | `0–59`; distinct per enabled env (FR-006c) |

Default fleet offsets: `macmini` production `:00` / staging `:15`;
`nuc` production `:30` / staging `:45`.

### Shared

| Variable | Default | Description |
|---|---|---|
| `DASHBOARD_PORT` | `8080` | Per-machine dashboard port |
| `FILE_SETTLE_SECONDS` | `10` | Min file age before it is claimed |
| `UPLOAD_TIMEOUT_SECONDS` | `30` | HTTP upload timeout |
| `UPLOAD_MAX_RETRIES` | `3` | Upload attempts per page (retries on 5xx) |
| `UPLOAD_RETRY_MAX_WAIT_SECONDS` | `10` | Exponential back-off cap |
| `LOG_LEVEL` | `INFO` | `DEBUG` / `INFO` / `WARNING` / `ERROR` |

## File lifecycle (per environment)

```
<ENV_<NAME>__WATCH_DIR>/
├── *.pdf | *.tiff          ← operator drops scans here
├── in-progress/
│   ├── macmini/            ← claimed & owned by macmini only
│   └── nuc/                ← claimed & owned by nuc only
└── processed/              ← terminal, shared across the fleet
```

A scan is claimed by atomic `rename` into `in-progress/<machine>/`
(exactly one machine wins; the loser sees it gone and moves on). On
every-page success it moves to the shared `processed/`; on failure it
returns to the watch folder for a later poll. At startup each machine
recovers only its **own** `in-progress/<machine>/` subfolder.

## Dashboard

`http://<machine-ip>:8080` — per machine, no cross-machine aggregation:

- Machine identity + NTP status banner (offset, outcome, drift warning)
- Side-by-side **production** / **staging** panes: backend host,
  schedule offset, current/last run progress, per-env error list
- Server-Sent Events; every event carries `env` + `machine`, plus
  `clock_sync` / `clock_drift_warning` events

## Development

```bash
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest --ignore=tests/contract --cov=scanner
.venv/bin/ruff check .
.venv/bin/mypy --strict scanner/
```

## Architecture

| Module | Role |
|---|---|
| `scanner/config.py` | `AppSettings`: `MachineIdentity` + `list[Environment]` + `NTPSettings`; startup validation → `ConfigError` |
| `scanner/machine.py` | Validated host identity; per-machine path resolution |
| `scanner/ntp.py` | `NTPClient` (offset), `NTPGate` (startup), `DriftMonitor` (recurring correction) |
| `scanner/state.py` | Per-`(machine, env)` `BatchRunState` (RLock); env+machine-tagging, secret-redacting logger |
| `scanner/pdf_processor.py` | PyMuPDF/PIL page extraction + two-tier orientation detection |
| `scanner/uploader.py` | Env-aware upload (`Bearer`, per-env host/token) with back-off retry |
| `scanner/batch.py` | `BatchRunner`: claim → process → upload → disposition, per env & machine |
| `scanner/scheduler.py` | One `CronTrigger` per enabled env; `max_instances=1` + `coalesce` |
| `scanner/dashboard.py` | FastAPI: multi-env `/status`, tagged SSE, env-scoped `POST /run` |
| `scanner/__main__.py` | Entry: config → NTP gate → recovery → dashboard → scheduler → drift monitor |

## Governance

Development follows the project Constitution
([`.specify/memory/constitution.md`](.specify/memory/constitution.md)),
**v3.0.0** — cross-platform (macOS + Linux) unattended operation,
test-driven development, quality-first, structured observability,
documentation before PR.
