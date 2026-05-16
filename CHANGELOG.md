# Changelog

All notable changes to pms-scanner are documented here. Format loosely
follows [Keep a Changelog](https://keepachangelog.com/).

## [0.4.0] — 2026-05-15 — Dual-Environment Upload Routing (feature 004)

### Added

- **Dual-environment routing**: `production` → `adg.mpsinc.io`,
  `staging` → `dev.adg.mpsinc.io`, decided solely by which watch folder
  a file lands in, with per-environment credentials (FR-001..005).
- **Multi-machine fleet**: self-declared `MACHINE_IDENTITY`; files are
  claimed by atomic rename into `in-progress/<machine>/`; crash recovery
  is strictly per-machine (FR-007/008/017/018).
- **Staggered concurrent scheduler**: one APScheduler `CronTrigger` per
  enabled env (`max_instances=1` + `coalesce=True`); default fleet
  stride macmini `:00`/`:15`, nuc `:30`/`:45` (FR-006/006a/006b/006c).
- **NTP discipline**: startup gate refuses to start on excess drift or
  an unreachable source; hourly drift check with an out-of-band
  privileged correction helper (FR-020..024).
- **New modules**: `scanner/machine.py`, `scanner/ntp.py`,
  `scanner/scheduler.py`.
- **Per-machine dashboard**: two-pane (production/staging) layout, NTP
  status banner, `env`+`machine`-tagged SSE plus `clock_sync` /
  `clock_drift_warning` events; env-scoped `POST /run?environment=` and
  concurrent no-arg fan-out.
- **Linux support**: `systemd --user` unit, `docs/systemd-setup.md`,
  Linux clock helper.
- `CHANGELOG.md`, this entry.

### Changed

- `scanner/config.py` rewritten to `AppSettings` (machine identity +
  `list[Environment]` + `NTPSettings`) with field-named `ConfigError`.
- `scanner/state.py` restructured to a per-`(machine, env)`
  `BatchRunState` (RLock) with an env/machine-tagging, secret-redacting
  logger adapter.
- `scanner/uploader.py` takes an explicit `Environment` (Bearer auth,
  per-env host/token) — no module-level config, no hard-coded host.
- `scanner/batch.py` `BatchRunner` is constructed per `(env, machine)`.
- launchd plist now `WaitForPaths` both env shares; `.env.example` and
  `docs/launchd-setup.md` updated for the multi-env schema + NTP.
- **Constitution amended to v3.0.0**: Principle I broadened from
  "macOS-only" to cross-platform unattended operation (macOS + Linux),
  with parallel launchd / systemd deployment standards and a
  documented privilege boundary for clock correction.

### Removed

- The 003-era single-environment compatibility shims in `config.py`,
  `state.py`, `uploader.py`, `batch.py`, and `dashboard.py` (legacy
  `Settings`/`settings`, `RunRecord`, `_legacy_upload_page`,
  `execute_run`, the flat-`WATCH_DIR`/`API_TOKEN` migration path, and
  the legacy `/status` shape). Internal `.env` files migrate to the
  `ENVIRONMENTS` + `ENV_<NAME>__*` schema; the 003 dashboard wire shape
  is intentionally not preserved.
