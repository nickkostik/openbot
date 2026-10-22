#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
asar="${GROKBOT_ASAR:-/opt/Grok Bot/resources/app.asar}"
patcher="${GROKBOT_SIDEBAR_PATCHER:-$script_dir/patch-sidebar-authority.py}"
log="${GROKBOT_SIDEBAR_LOG:-${XDG_STATE_HOME:-$HOME/.local/state}/openbot/sidebar-patches-watch.log}"
backups="${GROKBOT_ASAR_PATCH_BACKUPS:-$HOME/.local/share/openbot/desktop-sidebar-backups}"
alert="${GROKBOT_SIDEBAR_ALERT:-$script_dir/sidebar-patches-watch.alert}"
runtime_dir="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
lock="${runtime_dir}/grokbot-sidebar-patches.watch.lock"
service="${GROKBOT_DESKTOP_SERVICE:-grokbot-desktop.service}"

mkdir -p "$(dirname "$log")" "$(dirname "$alert")"
exec 9>"$lock"
flock -n 9 || exit 0

timestamp() {
  date -u +"%Y-%m-%dT%H:%M:%SZ"
}

before="$(sha256sum "$asar" | awk '{print $1}')"
if ! sudo -n /usr/bin/env "GROKBOT_ASAR=$asar" "GROKBOT_ASAR_PATCH_BACKUPS=$backups" /usr/bin/python3 "$patcher" >"${log}.last" 2>&1; then
  message="$(timestamp) patch failure: $(tail -n 1 "${log}.last" 2>/dev/null || true)"
  printf '%s\n' "$message" | tee -a "$log" >"$alert"
  exit 0
fi
after="$(sha256sum "$asar" | awk '{print $1}')"

if [[ "$before" != "$after" ]]; then
  printf '%s bundle changed %s -> %s; restarting %s\n' \
    "$(timestamp)" "$before" "$after" "$service" | tee -a "$log"
  rm -f "$alert"
  # A menu-launched Electron instance can own the singleton while this unit is
  # inactive. Stop that exact user's binary normally before starting the unit.
  if ! systemctl --user is-active --quiet "$service"; then
    /usr/bin/python3 - "$asar" <<'PY'
import os
import signal
import sys
import time
from pathlib import Path

binary = (Path(sys.argv[1]).parent.parent / "grok-bot").resolve()
owned = []
for entry in Path("/proc").glob("[0-9]*"):
    try:
        if entry.stat().st_uid != os.getuid() or (entry / "exe").resolve() != binary:
            continue
        command = (entry / "cmdline").read_bytes()
        if command and b"--type=" not in command:
            owned.append(entry)
    except OSError:
        continue
for entry in owned:
    try:
        os.kill(int(entry.name), signal.SIGTERM)
    except ProcessLookupError:
        pass
for _ in range(100):
    if not any(entry.exists() for entry in owned):
        break
    time.sleep(0.1)
else:
    raise SystemExit("normal quit timed out; refusing a second desktop instance")
PY
  fi
  systemctl --user restart "$service"
else
  rm -f "$alert"
fi
