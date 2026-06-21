#!/usr/bin/env bash
# Handy wrapper around `docker compose` that points ARIA_DATA_PATH at the right
# SMB mount point for the host OS:
#   - macOS : /Volumes/aria/ARIAscans   (launchd / Finder mount convention)
#   - Linux : /mnt/aria/ARIAscans       (systemd RequiresMountsFor convention)
#
# Override the auto-detected path by exporting ARIA_DATA_PATH before running,
# e.g.  ARIA_DATA_PATH=/custom/path ./scripts/dc.sh up -d
#
# All arguments are forwarded verbatim to `docker compose`, so this behaves
# like a drop-in:  ./scripts/dc.sh up -d  |  ./scripts/dc.sh logs -f  | etc.
set -euo pipefail

# Resolve repo root from this script's location so it works from any cwd.
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"

if [ -z "${ARIA_DATA_PATH:-}" ]; then
  case "$(uname -s)" in
    Darwin) ARIA_DATA_PATH="/Volumes/aria" ;;
    Linux)  ARIA_DATA_PATH="/mnt/smbshare" ;;
    *)
      echo "dc.sh: unsupported OS '$(uname -s)'. Set ARIA_DATA_PATH manually." >&2
      exit 1
      ;;
  esac
fi
export ARIA_DATA_PATH

echo "dc.sh: ARIA_DATA_PATH=$ARIA_DATA_PATH" >&2

exec docker compose -f "$REPO_ROOT/docker-compose.yml" "$@"
