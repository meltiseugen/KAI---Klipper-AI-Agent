#!/bin/sh
set -eu
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PYTHON="$SCRIPT_DIR/../../.venv/bin/python"
if [ ! -x "$PYTHON" ]; then PYTHON=python3; fi
if [ -n "${KLIPPERAI_MAINSAIL_STATE_DIR:-}" ]; then
  set -- --state-dir "$KLIPPERAI_MAINSAIL_STATE_DIR" "$@"
fi
ELEVATE=0
for option do
  case "$option" in --install-hook|--remove-hook) ELEVATE=1 ;; esac
done
for option do
  case "$option" in --help|-h) ELEVATE=0 ;; esac
done
if [ "$ELEVATE" = 1 ] && [ "$(id -u)" -ne 0 ] && [ "${KLIPPERAI_NO_SUDO:-0}" != 1 ]; then
  exec sudo "$PYTHON" "$SCRIPT_DIR/nav_cli.py" "$@"
fi
exec "$PYTHON" "$SCRIPT_DIR/nav_cli.py" "$@"
