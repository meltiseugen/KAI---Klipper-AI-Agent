#!/bin/sh
# All maintenance uses the same Python interpreter, lock and recovery state.
set -eu
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PYTHON="$SCRIPT_DIR/../../.venv/bin/python"
if [ ! -x "$PYTHON" ]; then PYTHON=python3; fi
READ_ONLY=0
for option do
  case "$option" in --check|--validate|-h|--help) READ_ONLY=1 ;; esac
done
STATE_DIR="${KLIPPERAI_STATE_DIR:-/etc/klipperai}"
if [ "$READ_ONLY" = 1 ] || [ "$(id -u)" -eq 0 ] || [ "${KLIPPERAI_NO_SUDO:-0}" = 1 ]; then
  exec "$PYTHON" "$SCRIPT_DIR/maintenance.py" --state-dir "$STATE_DIR" "$@"
fi
exec sudo "$PYTHON" "$SCRIPT_DIR/maintenance.py" --state-dir "$STATE_DIR" "$@"
