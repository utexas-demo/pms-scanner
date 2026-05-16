# Quickstart: pms-scanner on macOS

**Target**: macOS 13+ (Ventura or later), MedPath Wi-Fi, ARIA SMB share

---

## Prerequisites

### 1. Python 3.12

```bash
# Check version
python3 --version   # must be 3.12.x

# Install via Homebrew if needed
brew install python@3.12
```

### 2. Tesseract (orientation detection fallback)

```bash
brew install tesseract
tesseract --version   # confirm install
```

### 3. Mount the ARIA Share

Connect once in Finder: **⌘K** → `smb://adgligo2/aria` → **Connect** → select `ARIAscans`.

To auto-mount on login: **System Settings → General → Login Items** → add `/Volumes/aria`.

Verify mount:
```bash
ls /Volumes/aria/ARIAscans
```

---

## Installation

```bash
# Clone / navigate to repo
cd /path/to/pms-scanner

# Create virtual environment
python3.12 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

---

## Configuration

```bash
cp .env.example .env
```

Edit `.env` — required fields:

```dotenv
BACKEND_BASE_URL=https://api.example.com   # replace with real backend URL
API_TOKEN=your-jwt-token-here              # replace with real token

# Defaults that work for ARIA share — change only if needed:
WATCH_DIR=/Volumes/aria/ARIAscans
CRON_INTERVAL_SECONDS=60
DASHBOARD_PORT=8080
FILE_SETTLE_SECONDS=10
```

---

## Run Manually (Development)

```bash
source .venv/bin/activate
python -m scanner
```

Dashboard available at: `http://localhost:8080`

---

## Install as macOS Daemon (Production)

The daemon starts automatically at login and restarts on crash. It waits for the ARIA share to be mounted before beginning.

### 1. Customise the plist

Edit `launchd/io.mpsinc.pms-scanner.plist` — replace the two `REPLACE_ME` paths:

```xml
<!-- Replace with output of: which python3.12  (inside your venv) -->
<string>/path/to/pms-scanner/.venv/bin/python</string>

<!-- Replace with absolute path to repo -->
<string>WorkingDirectory → /path/to/pms-scanner</string>
```

### 2. Install the plist

```bash
cp launchd/io.mpsinc.pms-scanner.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/io.mpsinc.pms-scanner.plist
```

### 3. Verify

```bash
launchctl list | grep pms-scanner   # should show PID (not "-")
```

Dashboard: `http://localhost:8080` (or `http://<your-mac-ip>:8080` from other devices)

### 4. View Logs

```bash
tail -f /tmp/pms-scanner.log
```

### 5. Stop / Remove

```bash
launchctl unload ~/Library/LaunchAgents/io.mpsinc.pms-scanner.plist
```

---

## Folder Structure (Auto-Created)

```text
/Volumes/aria/ARIAscans/
├── *.pdf               ← drop scanned PDFs here
├── in-progress/        ← claimed by active run (auto-created)
└── processed/          ← completed files (auto-created)
```

Files that fail processing remain in `ARIAscans/` root for retry on the next run.

---

## Verify End-to-End

1. Drop a PDF into `/Volumes/aria/ARIAscans/`
2. Wait up to 60 seconds (one cron tick)
3. Open `http://localhost:8080` — watch progress in real time
4. Check `/Volumes/aria/ARIAscans/processed/` — file should appear after completion
5. Verify pages appear in backend system

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---------|-------------|-----|
| Dashboard not reachable | Daemon not running | `launchctl list \| grep pms-scanner` |
| Files not being picked up | SMB share not mounted | `ls /Volumes/aria/ARIAscans` |
| Files stuck in `in-progress/` | Process crashed mid-run | Auto-recovered on next run start; check logs |
| Orientation not corrected | Tesseract not installed | `brew install tesseract` |
| `401 Unauthorized` in logs | Invalid or expired API_TOKEN | Update `API_TOKEN` in `.env`; restart daemon |
