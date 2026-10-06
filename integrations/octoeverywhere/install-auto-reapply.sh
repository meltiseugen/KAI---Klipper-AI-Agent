#!/bin/sh

set -eu

usage() {
  cat <<'EOF'
Usage: install-auto-reapply.sh [options]

Install a systemd path/timer hook that coordinates the local KlipperAI patch
with Moonraker-managed OctoEverywhere updates. It removes only KlipperAI's
marked blocks when an update is pending, then reapplies them after the update.

Options:
  --install-dir PATH      KlipperAI checkout root. Default: auto-detected
  --oe-root PATH          OctoEverywhere checkout root. Default: /usr/data/octoeverywhere
  --klipperai-prefix PATH  Public KlipperAI prefix. Default: /klipperai
  --klipperai-port PORT    Local KlipperAI backend port. Default: 8811
  --nav-target VALUE      Sidebar click behavior: _blank or _self. Default: _blank
  --service NAME          OctoEverywhere systemd service. Default: octoeverywhere
  --moonraker-url URL      Moonraker base URL. Default: http://127.0.0.1:7125
  --update-manager NAME   Moonraker updater name. Default: octoeverywhere
  --interval VALUE        systemd fallback timer interval. Default: 5min
  -h, --help              Show this help
EOF
}

run_root() {
  if [ "$(id -u)" -eq 0 ] || [ "${KLIPPERAI_NO_SUDO:-0}" = "1" ]; then
    "$@"
    return
  fi

  if command -v sudo >/dev/null 2>&1; then
    sudo "$@"
    return
  fi

  printf 'sudo is required to run: %s\n' "$1" >&2
  exit 1
}

die() {
  printf '[KlipperAI OE auto-reapply] error: %s\n' "$*" >&2
  exit 1
}

ensure_no_spaces() {
  case "$2" in
    *" "*|*"	"*|*'"'*|*"'"*|*'`'*|*'$'*|*'\'*|*'
'*)
      die "$1 contains unsupported shell characters: $2"
      ;;
  esac
}

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
INSTALL_DIR=$(CDPATH= cd -- "$SCRIPT_DIR/../.." && pwd)
OE_ROOT="/usr/data/octoeverywhere"
KLIPPERAI_PREFIX="/klipperai"
KLIPPERAI_PORT="8811"
NAV_TARGET="_blank"
OE_SERVICE="octoeverywhere"
MOONRAKER_URL="http://127.0.0.1:7125"
OE_UPDATE_MANAGER="octoeverywhere"
CHECK_INTERVAL="5min"
RUNNER_PATH="${KLIPPERAI_OE_RUNNER_PATH:-/usr/local/bin/klipperai-octoeverywhere-reapply}"
SYSTEMD_DIR="${KLIPPERAI_SYSTEMD_DIR:-/etc/systemd/system}"
STATE_DIR="${KLIPPERAI_STATE_DIR:-/etc/klipperai}"
REAPPLY_SERVICE_NAME="klipperai-octoeverywhere-reapply.service"
REAPPLY_TIMER_NAME="klipperai-octoeverywhere-reapply.timer"
REAPPLY_PATH_NAME="klipperai-octoeverywhere-reapply.path"

while [ $# -gt 0 ]; do
  case "$1" in
    --install-dir)
      INSTALL_DIR="$2"
      shift 2
      ;;
    --oe-root)
      OE_ROOT="$2"
      shift 2
      ;;
    --klipperai-prefix)
      KLIPPERAI_PREFIX="$2"
      shift 2
      ;;
    --klipperai-port)
      KLIPPERAI_PORT="$2"
      shift 2
      ;;
    --nav-target)
      NAV_TARGET="$2"
      shift 2
      ;;
    --service)
      OE_SERVICE="$2"
      shift 2
      ;;
    --moonraker-url)
      MOONRAKER_URL="$2"
      shift 2
      ;;
    --update-manager)
      OE_UPDATE_MANAGER="$2"
      shift 2
      ;;
    --interval)
      CHECK_INTERVAL="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      printf 'Unknown argument: %s\n' "$1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

case "$KLIPPERAI_PREFIX" in
  "")
    KLIPPERAI_PREFIX="/klipperai"
    ;;
  /*)
    ;;
  *)
    KLIPPERAI_PREFIX="/$KLIPPERAI_PREFIX"
    ;;
esac

if [ "$KLIPPERAI_PREFIX" != "/" ]; then
  KLIPPERAI_PREFIX="${KLIPPERAI_PREFIX%/}"
fi

case "$KLIPPERAI_PORT" in
  ''|*[!0-9]*)
    die "Invalid --klipperai-port value: $KLIPPERAI_PORT"
    ;;
esac

case "$NAV_TARGET" in
  _blank|_self)
    ;;
  *)
    die "Invalid --nav-target value: $NAV_TARGET"
    ;;
esac

ensure_no_spaces "state directory" "$STATE_DIR"
ensure_no_spaces "runner path" "$RUNNER_PATH"
ensure_no_spaces "systemd directory" "$SYSTEMD_DIR"
ensure_no_spaces "--install-dir" "$INSTALL_DIR"
ensure_no_spaces "--oe-root" "$OE_ROOT"
ensure_no_spaces "--klipperai-prefix" "$KLIPPERAI_PREFIX"
ensure_no_spaces "--service" "$OE_SERVICE"
ensure_no_spaces "--moonraker-url" "$MOONRAKER_URL"
ensure_no_spaces "--update-manager" "$OE_UPDATE_MANAGER"
ensure_no_spaces "--interval" "$CHECK_INTERVAL"

[ -f "$INSTALL_DIR/integrations/octoeverywhere/apply-local-klipperai-route-patch.sh" ] || \
  die "Patch helper not found under $INSTALL_DIR"
[ -d "$OE_ROOT" ] || die "OctoEverywhere checkout not found: $OE_ROOT"
command -v systemctl >/dev/null 2>&1 || die "systemctl is required."

LEGACY_BACKUP_DIR="$STATE_DIR/octoeverywhere-backups/legacy"
LEGACY_BACKUP_COUNT=0
for legacy_backup in \
  "$OE_ROOT"/moonraker_octoeverywhere/moonrakerapirouter.py.klippyai-backup-* \
  "$OE_ROOT"/moonraker_octoeverywhere/static/oe-ui.js.klippyai-backup-*
do
  [ -f "$legacy_backup" ] || continue
  run_root install -d -m 755 "$LEGACY_BACKUP_DIR"
  run_root mv "$legacy_backup" "$LEGACY_BACKUP_DIR/$(basename "$legacy_backup")"
  LEGACY_BACKUP_COUNT=$((LEGACY_BACKUP_COUNT + 1))
done
if [ "$LEGACY_BACKUP_COUNT" -gt 0 ]; then
  printf '[KlipperAI OE auto-reapply] Moved %s legacy backup file(s) out of the OctoEverywhere checkout.\n' "$LEGACY_BACKUP_COUNT"
fi

OE_SERVICE_UNIT="$OE_SERVICE"
case "$OE_SERVICE_UNIT" in
  *.service)
    ;;
  *)
    OE_SERVICE_UNIT="${OE_SERVICE_UNIT}.service"
    ;;
esac

RUNNER_TMP=$(mktemp)
SERVICE_TMP=$(mktemp)
TIMER_TMP=$(mktemp)
PATH_TMP=$(mktemp)
cleanup() {
  rm -f "$RUNNER_TMP" "$SERVICE_TMP" "$TIMER_TMP" "$PATH_TMP"
}
trap cleanup EXIT

cat >"$RUNNER_TMP" <<EOF
#!/bin/sh

set -eu

INSTALL_DIR="$INSTALL_DIR"
OE_ROOT="$OE_ROOT"
KLIPPERAI_PREFIX="$KLIPPERAI_PREFIX"
KLIPPERAI_PORT="$KLIPPERAI_PORT"
NAV_TARGET="$NAV_TARGET"
OE_SERVICE="$OE_SERVICE"
MOONRAKER_URL="$MOONRAKER_URL"
OE_UPDATE_MANAGER="$OE_UPDATE_MANAGER"
export KLIPPERAI_STATE_DIR="$STATE_DIR"
SUSPEND_FILE="$STATE_DIR/octoeverywhere-reapply.suspended"

. "\$INSTALL_DIR/integrations/octoeverywhere/reapply.sh"
EOF

cat >"$SERVICE_TMP" <<EOF
[Unit]
Description=Reapply KlipperAI OctoEverywhere local route patch when missing
After=network-online.target $OE_SERVICE_UNIT
Wants=network-online.target

[Service]
Type=oneshot
ExecStart=$RUNNER_PATH
EOF

cat >"$TIMER_TMP" <<EOF
[Unit]
Description=Check whether the KlipperAI OctoEverywhere patch still exists

[Timer]
OnBootSec=2min
OnUnitActiveSec=$CHECK_INTERVAL
AccuracySec=5min
Persistent=true

[Install]
WantedBy=timers.target
EOF

cat >"$PATH_TMP" <<EOF
[Unit]
Description=Watch OctoEverywhere files for KlipperAI patch replacement

[Path]
PathChanged=$OE_ROOT/moonraker_octoeverywhere/moonrakerapirouter.py
PathChanged=$OE_ROOT/moonraker_octoeverywhere/static/oe-ui.js
Unit=$REAPPLY_SERVICE_NAME

[Install]
WantedBy=multi-user.target
EOF

run_root install -d -m 755 "$(dirname "$RUNNER_PATH")" "$SYSTEMD_DIR"
run_root install -m 755 "$RUNNER_TMP" "$RUNNER_PATH"
run_root install -m 644 "$SERVICE_TMP" "$SYSTEMD_DIR/$REAPPLY_SERVICE_NAME"
run_root install -m 644 "$TIMER_TMP" "$SYSTEMD_DIR/$REAPPLY_TIMER_NAME"
run_root install -m 644 "$PATH_TMP" "$SYSTEMD_DIR/$REAPPLY_PATH_NAME"
run_root systemctl daemon-reload
run_root "$RUNNER_PATH"
run_root systemctl enable --now "$REAPPLY_TIMER_NAME"
run_root systemctl enable --now "$REAPPLY_PATH_NAME"

printf '[KlipperAI OE auto-reapply] Installed %s\n' "$RUNNER_PATH"
printf '[KlipperAI OE auto-reapply] Installed %s/%s\n' "$SYSTEMD_DIR" "$REAPPLY_SERVICE_NAME"
printf '[KlipperAI OE auto-reapply] Installed %s/%s\n' "$SYSTEMD_DIR" "$REAPPLY_TIMER_NAME"
printf '[KlipperAI OE auto-reapply] Installed %s/%s\n' "$SYSTEMD_DIR" "$REAPPLY_PATH_NAME"
printf '[KlipperAI OE auto-reapply] Timer interval: %s\n' "$CHECK_INTERVAL"
