#!/bin/sh

set -eu

usage() {
  cat <<'EOF'
Usage: apply-local-klipperai-route-patch.sh [options]

Patch a local OctoEverywhere checkout so the main OctoEverywhere portal can
forward /klipperai/... to the local KlipperAI backend and force a full browser
navigation from the injected frontend helper.

Options:
  --oe-root PATH          OctoEverywhere checkout root. Default: $HOME/octoeverywhere
  --klipperai-prefix PATH  Public KlipperAI prefix. Default: /klipperai
  --klipperai-port PORT    Local KlipperAI backend port. Default: 8811
  --nav-target VALUE      Sidebar click behavior: _blank or _self. Default: _blank
  --restart-service       Restart the OctoEverywhere systemd service after patching
  --service NAME          Service name to restart with --restart-service. Default: octoeverywhere
  --restore-original      Remove KlipperAI patch blocks before an OctoEverywhere update
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

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
OE_ROOT="${HOME:-}/octoeverywhere"
KLIPPERAI_PREFIX="/klipperai"
KLIPPERAI_PORT="8811"
NAV_TARGET="_blank"
RESTART_SERVICE=0
OE_SERVICE="octoeverywhere"
RESTORE_ORIGINAL=0
STATE_DIR="${KLIPPERAI_STATE_DIR:-/etc/klipperai}"
SUSPEND_FILE="$STATE_DIR/octoeverywhere-reapply.suspended"
BACKUP_DIR="$STATE_DIR/octoeverywhere-backups"

while [ $# -gt 0 ]; do
  case "$1" in
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
    --restart-service)
      RESTART_SERVICE=1
      shift
      ;;
    --service)
      OE_SERVICE="$2"
      shift 2
      ;;
    --restore-original|--restore)
      RESTORE_ORIGINAL=1
      shift
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
    printf 'Invalid --klipperai-port value: %s\n' "$KLIPPERAI_PORT" >&2
    exit 1
    ;;
esac

case "$NAV_TARGET" in
  _blank|_self)
    ;;
  *)
    printf 'Invalid --nav-target value: %s\n' "$NAV_TARGET" >&2
    exit 1
    ;;
esac

ROUTER_FILE="$OE_ROOT/moonraker_octoeverywhere/moonrakerapirouter.py"
UI_FILE="$OE_ROOT/moonraker_octoeverywhere/static/oe-ui.js"
ROUTER_TMP="$(mktemp)"
UI_TMP="$(mktemp)"
SUSPEND_TMP="$(mktemp)"

cleanup() {
  rm -f "$ROUTER_TMP" "$UI_TMP" "$SUSPEND_TMP"
}
trap cleanup EXIT

if [ ! -f "$ROUTER_FILE" ]; then
  printf 'OctoEverywhere router file not found: %s\n' "$ROUTER_FILE" >&2
  exit 1
fi

if [ ! -f "$UI_FILE" ]; then
  printf 'OctoEverywhere injected UI helper not found: %s\n' "$UI_FILE" >&2
  exit 1
fi

backup_file_to_dir() {
  source_path="$1"
  label="$2"
  backup_path="$BACKUP_DIR/$label.$STAMP"
  run_root install -d -m 755 "$BACKUP_DIR"
  run_root cp "$source_path" "$backup_path"
  printf '%s' "$backup_path"
}

if [ "$RESTORE_ORIGINAL" -eq 1 ]; then
  STAMP="$(date +%Y%m%d-%H%M%S)"
  ROUTER_BACKUP="$(backup_file_to_dir "$ROUTER_FILE" "moonrakerapirouter.py.restore-backup")"
  UI_BACKUP="$(backup_file_to_dir "$UI_FILE" "oe-ui.js.restore-backup")"

  OE_ROUTER_FILE="$ROUTER_FILE" \
  OE_UI_FILE="$UI_FILE" \
  OE_ROUTER_OUTPUT_FILE="$ROUTER_TMP" \
  OE_UI_OUTPUT_FILE="$UI_TMP" \
  python3 "$SCRIPT_DIR/route_patch.py" --restore

  ROUTER_CHANGED=0
  UI_CHANGED=0
  cmp -s "$ROUTER_FILE" "$ROUTER_TMP" || ROUTER_CHANGED=1
  cmp -s "$UI_FILE" "$UI_TMP" || UI_CHANGED=1

  if [ "$ROUTER_CHANGED" -eq 1 ]; then
    cat "$ROUTER_TMP" >"$ROUTER_FILE"
  fi
  if [ "$UI_CHANGED" -eq 1 ]; then
    cat "$UI_TMP" >"$UI_FILE"
  fi

  {
    printf 'KlipperAI OctoEverywhere auto-reapply is suspended for an OctoEverywhere update.\n'
    printf 'Created: %s\n' "$STAMP"
    printf 'Reapply the KlipperAI patch after updating OctoEverywhere to remove this file.\n'
  } >"$SUSPEND_TMP"
  run_root install -d -m 755 "$(dirname "$SUSPEND_FILE")"
  run_root install -m 644 "$SUSPEND_TMP" "$SUSPEND_FILE"

  printf 'Removed KlipperAI patch blocks from OctoEverywhere at %s\n' "$OE_ROOT"
  printf '  Router backup: %s\n' "$ROUTER_BACKUP"
  printf '  UI backup:     %s\n' "$UI_BACKUP"
  printf '  Router edit:   %s\n' "$( [ "$ROUTER_CHANGED" -eq 1 ] && printf changed || printf unchanged )"
  printf '  UI edit:       %s\n' "$( [ "$UI_CHANGED" -eq 1 ] && printf changed || printf unchanged )"
  printf '  Auto-reapply suspended by: %s\n' "$SUSPEND_FILE"
  if [ "$RESTART_SERVICE" -eq 1 ]; then
    run_root systemctl restart "$OE_SERVICE"
    printf 'Restarted systemd service: %s\n' "$OE_SERVICE"
  fi
  printf 'Next steps:\n'
  printf '  1. Update OctoEverywhere from Mainsail/Moonraker.\n'
  printf '  2. Re-run this script without --restore-original to reapply KlipperAI.\n'
  exit 0
fi

OE_ROUTER_FILE="$ROUTER_FILE" \
OE_UI_FILE="$UI_FILE" \
OE_ROUTER_OUTPUT_FILE="$ROUTER_TMP" \
OE_UI_OUTPUT_FILE="$UI_TMP" \
KLIPPERAI_PREFIX="$KLIPPERAI_PREFIX" \
KLIPPERAI_PORT="$KLIPPERAI_PORT" \
NAV_TARGET="$NAV_TARGET" \
python3 "$SCRIPT_DIR/route_patch.py"

ROUTER_CHANGED=0
UI_CHANGED=0
if ! cmp -s "$ROUTER_FILE" "$ROUTER_TMP"; then
  ROUTER_CHANGED=1
fi
if ! cmp -s "$UI_FILE" "$UI_TMP"; then
  UI_CHANGED=1
fi

if [ "$ROUTER_CHANGED" -eq 0 ] && [ "$UI_CHANGED" -eq 0 ]; then
  printf 'OctoEverywhere checkout already matches the KlipperAI patch: %s\n' "$OE_ROOT"
  printf '  Router file: %s\n' "$ROUTER_FILE"
  printf '  UI helper:   %s\n' "$UI_FILE"
  printf '  Route:       %s/ -> http://127.0.0.1:%s/\n' "$KLIPPERAI_PREFIX" "$KLIPPERAI_PORT"
  printf '  Nav target:  %s\n' "$NAV_TARGET"
  if [ "$RESTART_SERVICE" -eq 1 ]; then
    run_root systemctl restart "$OE_SERVICE"
    printf 'Restarted systemd service: %s\n' "$OE_SERVICE"
  fi
  if [ -f "$SUSPEND_FILE" ]; then
    run_root rm -f "$SUSPEND_FILE"
    printf 'Resumed OctoEverywhere auto-reapply by removing: %s\n' "$SUSPEND_FILE"
  fi
  exit 0
fi

STAMP="$(date +%Y%m%d-%H%M%S)"
if [ "$ROUTER_CHANGED" -eq 1 ]; then
  ROUTER_BACKUP="$(backup_file_to_dir "$ROUTER_FILE" "moonrakerapirouter.py.patch-backup")"
  cat "$ROUTER_TMP" >"$ROUTER_FILE"
fi
if [ "$UI_CHANGED" -eq 1 ]; then
  UI_BACKUP="$(backup_file_to_dir "$UI_FILE" "oe-ui.js.patch-backup")"
  cat "$UI_TMP" >"$UI_FILE"
fi

printf 'Patched OctoEverywhere checkout at %s\n' "$OE_ROOT"
printf '  Router file: %s\n' "$ROUTER_FILE"
printf '  UI helper:   %s\n' "$UI_FILE"
printf '  Route:       %s/ -> http://127.0.0.1:%s/\n' "$KLIPPERAI_PREFIX" "$KLIPPERAI_PORT"
printf '  Nav target:  %s\n' "$NAV_TARGET"
printf '  Router edit: %s\n' "$( [ "$ROUTER_CHANGED" -eq 1 ] && printf changed || printf unchanged )"
printf '  UI edit:     %s\n' "$( [ "$UI_CHANGED" -eq 1 ] && printf changed || printf unchanged )"
[ "$ROUTER_CHANGED" -eq 1 ] && printf '  Router backup: %s\n' "$ROUTER_BACKUP"
[ "$UI_CHANGED" -eq 1 ] && printf '  UI backup:     %s\n' "$UI_BACKUP"

if [ "$RESTART_SERVICE" -eq 1 ]; then
  run_root systemctl restart "$OE_SERVICE"
  printf 'Restarted systemd service: %s\n' "$OE_SERVICE"
fi

if [ -f "$SUSPEND_FILE" ]; then
  run_root rm -f "$SUSPEND_FILE"
  printf 'Resumed OctoEverywhere auto-reapply by removing: %s\n' "$SUSPEND_FILE"
fi

printf 'Next steps:\n'
printf '  1. Hard-refresh the OctoEverywhere portal.\n'
printf '  2. Open %s/ through the main OctoEverywhere printer URL.\n' "$KLIPPERAI_PREFIX"
printf '  3. If the browser still shows cached Mainsail shell content, retry in an incognito tab.\n'
