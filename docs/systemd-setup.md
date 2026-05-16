# Linux (NUC) systemd Setup Guide (dual-environment, 004)

Installs pms-scanner on a Debian 12+/Ubuntu 22.04+ host as a
**`systemd --user`** service that:

- Restarts automatically (`Restart=always`, `RestartSec=10`)
- Waits for **both** environment SMB mounts (`RequiresMountsFor=`)
- Runs **unprivileged**; clock correction (if enabled) is delegated to
  a narrowly scoped out-of-band helper

Source of truth for configuration: `.env.example` and
`specs/004-multi-env-uploads/contracts/config-schema.md`.

---

## Prerequisites

1. Python 3.12+ and Tesseract (`sudo apt install python3.12 python3.12-venv tesseract-ocr`)
2. `cifs-utils` for the SMB mounts (`sudo apt install cifs-utils`)
3. API tokens for both environments
4. A working host time-sync service (`systemd-timesyncd` or `chrony`)
   so the NTP startup gate passes

---

## 1. Mount both shares via /etc/fstab

Store the SMB credentials root-only:

```bash
sudo install -m 600 /dev/stdin /etc/aria-smb.cred <<'EOF'
username=ARIAUSER
password=ARIAPASS
domain=ARIADOMAIN
EOF
```

Add to `/etc/fstab` (one line per share). `_netdev` waits for the
network; `x-systemd.automount` mounts lazily on first access and lets
`RequiresMountsFor=` work cleanly:

```fstab
//aria/ARIAscans-prod     /mnt/aria/ARIAscans-prod     cifs  credentials=/etc/aria-smb.cred,uid=%U,gid=%G,vers=3.0,_netdev,x-systemd.automount,nofail  0 0
//aria/ARIAscans-staging  /mnt/aria/ARIAscans-staging  cifs  credentials=/etc/aria-smb.cred,uid=%U,gid=%G,vers=3.0,_netdev,x-systemd.automount,nofail  0 0
```

```bash
sudo mkdir -p /mnt/aria/ARIAscans-prod /mnt/aria/ARIAscans-staging
sudo systemctl daemon-reload
ls /mnt/aria/ARIAscans-prod   # triggers the automount
```

---

## 2. Install pms-scanner

```bash
git clone https://github.com/mpsinc/pms-scanner.git ~/pms-scanner
cd ~/pms-scanner
python3.12 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

Create `~/.config/pms-scanner/.env` from `.env.example`. On the NUC use
the Linux mount paths and the nuc offsets:

```env
MACHINE_IDENTITY=nuc
ENVIRONMENTS=production,staging
ENV_PRODUCTION__WATCH_DIR=/mnt/aria/ARIAscans-prod
ENV_PRODUCTION__BACKEND_BASE_URL=https://adg.mpsinc.io
ENV_PRODUCTION__API_TOKEN=<prod-token>
ENV_PRODUCTION__SCHEDULE_OFFSET_SECONDS=30
ENV_STAGING__WATCH_DIR=/mnt/aria/ARIAscans-staging
ENV_STAGING__BACKEND_BASE_URL=https://dev.adg.mpsinc.io
ENV_STAGING__API_TOKEN=<staging-token>
ENV_STAGING__SCHEDULE_OFFSET_SECONDS=45
NTP__SOURCE=pool.ntp.org
NTP__MAX_DRIFT_SECONDS=1.0
```

`chmod 600 ~/.config/pms-scanner/.env` — it holds both API tokens.

---

## 3. Install the user unit

```bash
mkdir -p ~/.config/systemd/user
cp systemd/pms-scanner.service ~/.config/systemd/user/
# Adjust WorkingDirectory/ExecStart if the repo/venv differ from
# ~/pms-scanner and ~/pms-scanner/.venv.
systemctl --user daemon-reload
systemctl --user enable --now pms-scanner.service
systemctl --user status pms-scanner.service
```

Let the user manager run without an active login session so the service
survives logout/reboot:

```bash
sudo loginctl enable-linger "$USER"
```

Open `http://<nuc-ip>:8080` for the dashboard.

---

## 4. NTP startup gate

Identical semantics to macOS: on start, offset is measured against
`NTP__SOURCE`; if it exceeds `NTP__MAX_DRIFT_SECONDS` or the source is
unreachable the service **refuses to start** (FR-022/024). Keep
`systemd-timesyncd`/`chrony` healthy:

```bash
timedatectl status        # "System clock synchronized: yes"
```

`NTP__STARTUP_REQUIRED=false` is local-dev only (startup WARNING).

---

## 5. Optional: privileged clock-correction helper

```bash
sudo cp scripts/linux/pms-scanner-correct-clock /usr/local/libexec/
sudo chmod 755 /usr/local/libexec/pms-scanner-correct-clock
```

Narrowly scoped sudoers (`sudo visudo -f /etc/sudoers.d/pms-scanner`):

```sudoers
youruser ALL=(root) NOPASSWD: /usr/local/libexec/pms-scanner-correct-clock
```

The helper runs `chronyc makestep` (or falls back to `timedatectl
set-time`). If absent or failing the daemon logs a WARNING and
continues on the last-known-good clock.

---

## 6. Journal inspection

```bash
journalctl --user -u pms-scanner -f
journalctl --user -u pms-scanner --since "10 min ago" | grep 'env=staging'
```

Every line is tagged `[machine=nuc env=…]`; API tokens are redacted.

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `start request repeated too quickly` | Crash loop (config/NTP) | `journalctl --user -u pms-scanner -n50` — fix the named error |
| Stuck `activating (start)` | A `RequiresMountsFor` mount missing | `ls /mnt/aria/ARIAscans-*`; check fstab + network |
| Service dies on logout | Lingering disabled | `sudo loginctl enable-linger "$USER"` |
| Refuses to start, ERROR names offset | NTP gate failed | Repair `timedatectl`/chrony or install the helper |
| One env idle | `ENV_*__ENABLED=false` or mount missing | Re-enable / remount that env's share |
