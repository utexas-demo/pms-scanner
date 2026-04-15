# macOS launchd Setup Guide

This guide installs pms-scanner as a macOS LaunchAgent so it:

- Starts automatically at login
- Restarts automatically if it crashes
- Waits for the `/Volumes/aria/ARIAscans` SMB share to mount before starting

---

## Prerequisites

1. Python 3.12+ installed (via pyenv, Homebrew, or the official installer)
2. Tesseract OCR installed: `brew install tesseract`
3. The ARIA SMB share configured to auto-mount at `/Volumes/aria/ARIAscans` (see [SMB Auto-Mount](#smb-auto-mount) below)
4. Project cloned to a known path (e.g. `~/Projects/utexas/pms-scanner`)

---

## Installation Steps

### 1. Create the virtual environment and install dependencies

```bash
cd ~/Projects/utexas/pms-scanner
python3.12 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

### 2. Create the `.env` file with required secrets

```bash
cp .env.example .env
# Edit .env and set:
#   BACKEND_BASE_URL=https://your-backend.example.com
#   API_TOKEN=your-jwt-token-here
#   WATCH_DIR=/Volumes/aria/ARIAscans
```

### 3. Customise the plist

Edit `launchd/io.mpsinc.pms-scanner.plist` and replace every occurrence of
`YOUR_USERNAME` with your actual macOS username:

```bash
sed -i '' "s/YOUR_USERNAME/$(whoami)/g" launchd/io.mpsinc.pms-scanner.plist
```

Verify the paths are correct:
- `ProgramArguments[0]` → `.venv/bin/python` inside the repo
- `WorkingDirectory` → the repo root
- `WaitForPaths` → the SMB share mount path

### 4. Copy the plist to the LaunchAgents directory

```bash
cp launchd/io.mpsinc.pms-scanner.plist \
   ~/Library/LaunchAgents/io.mpsinc.pms-scanner.plist
```

### 5. Load the service

```bash
launchctl load ~/Library/LaunchAgents/io.mpsinc.pms-scanner.plist
```

The service will start automatically once the SMB share mounts.

### 6. Verify the service is running

```bash
launchctl list | grep pms-scanner
```

Expected output (PID column non-zero means it is running):
```
12345  0  io.mpsinc.pms-scanner
```

Open the dashboard in a browser: http://localhost:8080

---

## SMB Auto-Mount

To ensure the ARIA share mounts automatically at login:

1. Open **System Settings → General → Login Items & Extensions**
2. Scroll down to **Network Drives**
3. Click **+** and add the server: `smb://aria/ARIAscans`

Alternatively, add it to `/etc/auto_master`:
```
/Volumes/aria  auto_aria  -nosuid,noowners
```

With `/etc/auto_aria` containing:
```
ARIAscans  -fstype=smbfs  smb://DOMAIN;user@aria/ARIAscans
```

---

## Viewing Logs

```bash
# Combined output
tail -f /tmp/pms-scanner.log

# Errors only
tail -f /tmp/pms-scanner.error.log

# launchd system log (macOS Ventura+)
log show --predicate 'subsystem == "com.apple.launchd"' --last 10m | grep pms-scanner
```

---

## Stopping and Unloading the Service

```bash
# Temporary stop (launchd will restart it on next login)
launchctl stop io.mpsinc.pms-scanner

# Permanent unload (remove from auto-start)
launchctl unload ~/Library/LaunchAgents/io.mpsinc.pms-scanner.plist
```

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---------|-------------|-----|
| `launchctl list` shows PID 0 or exit code | Service crashed at startup | Check `/tmp/pms-scanner.error.log` |
| Dashboard not reachable at :8080 | Port in use or wrong DASHBOARD_PORT | Check `.env` and that no other process owns port 8080 |
| No files processed after drop | SMB share not mounted | Run `ls /Volumes/aria/ARIAscans`; re-mount if empty |
| `ModuleNotFoundError` in logs | venv path mismatch in plist | Verify `ProgramArguments[0]` path exists |
| Files stuck in `in-progress/` | Process killed mid-run | Delete or move the stuck files; they auto-recover on next start |
| `TesseractNotFoundError` in logs | Tesseract not on PATH | `brew install tesseract`; ensure `/usr/local/bin` is in PATH in the plist |

---

## Updating the Service

After pulling new code:

```bash
cd ~/Projects/utexas/pms-scanner
git pull
.venv/bin/pip install -r requirements.txt
launchctl stop  io.mpsinc.pms-scanner
launchctl start io.mpsinc.pms-scanner
```
