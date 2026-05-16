# macOS launchd Setup Guide (dual-environment, 004)

Installs pms-scanner as a macOS LaunchAgent so it:

- Starts automatically at login and restarts if it crashes (`KeepAlive`)
- Waits for **both** environment SMB shares to mount before starting
  (`WaitForPaths`)
- Routes production scans to `adg.mpsinc.io` and staging scans to
  `dev.adg.mpsinc.io` using per-environment credentials
- Refuses to start until its clock is verified against NTP (the startup
  gate), and re-checks drift hourly thereafter

Source of truth for configuration: `.env.example` and
`specs/004-multi-env-uploads/contracts/config-schema.md`.

---

## Prerequisites

1. Python 3.12+ and Tesseract OCR (`brew install python@3.12 tesseract`)
2. Both ARIA SMB shares auto-mounting:
   - `/Volumes/aria/ARIAscans-prod`
   - `/Volumes/aria/ARIAscans-staging`
3. Project cloned to a known path (e.g. `~/Projects/utexas/pms-scanner`)
4. API tokens for **both** environments
5. macOS "Set date and time automatically" enabled (System Settings →
   General → Date & Time) so the NTP gate passes without a helper

---

## Installation

### 1. Virtual environment

```bash
cd ~/Projects/utexas/pms-scanner
python3.12 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

### 2. Configuration

```bash
cp .env.example .env
# Edit .env — set MACHINE_IDENTITY, the two ENV_<NAME>__* blocks
# (WATCH_DIR, BACKEND_BASE_URL, API_TOKEN, SCHEDULE_OFFSET_SECONDS) and
# the NTP__* block. NEVER commit the filled-in .env.
```

Default fleet offsets (operator-coordinated, set per host):

| Machine | production | staging |
|---|---|---|
| macmini | `:00` | `:15` |
| nuc | `:30` | `:45` |

### 3. Customise the plist

```bash
sed -i '' "s/YOUR_USERNAME/$(whoami)/g" launchd/io.mpsinc.pms-scanner.plist
```

Verify:
- `ProgramArguments[0]` → `.venv/bin/python` inside the repo
- `WorkingDirectory` → repo root (so a local `.env` is found)
- `WaitForPaths` → **both** env watch dirs
- `EnvironmentVariables` contains the non-secret routing/NTP keys; the
  two `ENV_*__API_TOKEN`s are **deliberately absent** (the XML is
  world-readable) and must live only in `.env`

### 4. Install and load

```bash
cp launchd/io.mpsinc.pms-scanner.plist ~/Library/LaunchAgents/
launchctl bootstrap gui/$UID ~/Library/LaunchAgents/io.mpsinc.pms-scanner.plist
launchctl enable gui/$UID/io.mpsinc.pms-scanner
launchctl list | grep pms-scanner
```

Open `http://<machine-ip>:8080` — the dashboard shows both environments
with the NTP status banner.

---

## NTP startup gate

On start, pms-scanner queries `NTP__SOURCE` and measures clock offset:

- offset within `NTP__MAX_DRIFT_SECONDS` → starts normally
- offset exceeds the threshold, or the source is unreachable → it
  **refuses to start**, logging one ERROR line naming the measured
  offset and the source (FR-022 / FR-024)

Fix by enabling automatic date & time, pointing `NTP__SOURCE` at a
reachable server, or installing the clock-correction helper below.

For local development only you may set `NTP__STARTUP_REQUIRED=false`
(emits a startup WARNING; the fleet stride is then unverified).

---

## Optional: privileged clock-correction helper

By default the daemon only *verifies* the clock and warns on drift. To
let it actively correct drift, install the out-of-band helper (the main
process stays unprivileged):

```bash
sudo cp scripts/macos/pms-scanner-correct-clock /usr/local/libexec/
sudo chmod 755 /usr/local/libexec/pms-scanner-correct-clock
```

Grant a **narrowly scoped** sudoers entry so the unprivileged daemon
may run only this one command (`sudo visudo -f /etc/sudoers.d/pms-scanner`):

```sudoers
youruser ALL=(root) NOPASSWD: /usr/local/libexec/pms-scanner-correct-clock
```

Point `NTP__CORRECT_CLOCK_COMMAND` at it (default already matches). The
helper runs `sntp -sS <source>`. If absent or failing, the daemon logs
a WARNING and continues on the last-known-good clock.

---

## SMB auto-mount

System Settings → General → Login Items & Extensions → Network Drives →
add `smb://aria/ARIAscans-prod` and `smb://aria/ARIAscans-staging`. Or
via `/etc/auto_master` + an `auto_aria` map listing both shares.

---

## Logs

```bash
tail -f /tmp/pms-scanner.log
tail -f /tmp/pms-scanner.error.log
```

Every log line is tagged `[machine=… env=…]` so production and staging
are distinguishable at a glance; API tokens are always redacted.

---

## Stop / unload / update

```bash
launchctl stop io.mpsinc.pms-scanner
launchctl bootout gui/$UID ~/Library/LaunchAgents/io.mpsinc.pms-scanner.plist

cd ~/Projects/utexas/pms-scanner && git pull
.venv/bin/pip install -r requirements.txt
launchctl kickstart -k gui/$UID/io.mpsinc.pms-scanner
```

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Refuses to start, ERROR names offset+source | NTP gate failed | Enable auto date/time, fix `NTP__SOURCE`, or install the helper |
| Refuses to start, ConfigError naming a field | Bad/missing config | Fix the named `ENV_*` / `MACHINE_IDENTITY` / offset; envs need distinct watch dirs and offsets |
| `launchctl list` shows non-zero exit | Crash at startup | Check `/tmp/pms-scanner.error.log` |
| One env idle, other works | That env disabled or share unmounted | Check `ENV_*__ENABLED` and `ls` both watch dirs |
| Files stuck in `in-progress/<machine>/` | Process killed mid-run | They auto-recover for **this** machine on next start |
| `TesseractNotFoundError` | Tesseract off PATH | `brew install tesseract`; keep `/usr/local/bin` in the plist PATH |
