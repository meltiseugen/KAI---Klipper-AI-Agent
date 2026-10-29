#!/bin/sh
# POSIX-only: this module must work before Bash or Python has been installed.

bootstrap_error() {
  printf '[KlipperAI] error: %s\n' "$*" >&2
  return 1
}

bootstrap_command_path() { command -v "$1" 2>/dev/null; }

bootstrap_opt_path() {
  PATH="/opt/bin:/opt/sbin:$PATH"
  export PATH
}

bootstrap_run_root() {
  if [ "$(id -u)" -eq 0 ]; then "$@"; else sudo "$@"; fi
}

bootstrap_is_creality() {
  [ -d /etc/init.d ] && [ "$(cat /proc/1/comm 2>/dev/null)" != systemd ] || return 1
  for bootstrap_printer_data in /usr/data/printer_data /usr/data/printer_1_data /usr/data/printer_2_data /usr/data/printer_3_data; do
    [ ! -d "$bootstrap_printer_data" ] || return 0
  done
  return 1
}

bootstrap_manager() {
  bootstrap_opt_path
  if bootstrap_is_creality && bootstrap_command_path opkg >/dev/null; then
    KLIPPERAI_PACKAGE_MANAGER=opkg
  elif bootstrap_command_path apt-get >/dev/null; then
    KLIPPERAI_PACKAGE_MANAGER=apt-get
  elif bootstrap_command_path opkg >/dev/null; then
    KLIPPERAI_PACKAGE_MANAGER=opkg
  elif bootstrap_command_path apk >/dev/null; then
    KLIPPERAI_PACKAGE_MANAGER=apk
  elif bootstrap_is_creality; then
    bootstrap_entware || return 1
    KLIPPERAI_PACKAGE_MANAGER=opkg
  else
    bootstrap_error 'No supported package manager found (apt-get, opkg or apk).'
    return 1
  fi
}

bootstrap_packages() {
  [ "$#" -gt 0 ] || return 0
  bootstrap_manager || return 1
  printf '[KlipperAI] Installing missing prerequisites with %s: %s\n' "$KLIPPERAI_PACKAGE_MANAGER" "$*"
  if [ "${KLIPPERAI_PACKAGE_INDEX_FOR:-}" != "$KLIPPERAI_PACKAGE_MANAGER" ]; then
    bootstrap_run_root "$KLIPPERAI_PACKAGE_MANAGER" update || return 1
    KLIPPERAI_PACKAGE_INDEX_FOR="$KLIPPERAI_PACKAGE_MANAGER"
    export KLIPPERAI_PACKAGE_INDEX_FOR
  fi
  case "$KLIPPERAI_PACKAGE_MANAGER" in
    apt-get) bootstrap_run_root apt-get install -y "$@" ;;
    opkg) bootstrap_run_root opkg install "$@" ;;
    apk) bootstrap_run_root apk add "$@" ;;
  esac
}

bootstrap_bash() {
  bootstrap_opt_path
  if bootstrap_command_path bash >/dev/null; then return 0; fi
  [ "$(uname -s)" = Linux ] || { bootstrap_error 'Automatic prerequisite setup requires Linux.'; return 1; }
  bootstrap_packages bash || return 1
  hash -r 2>/dev/null || true
  bootstrap_command_path bash >/dev/null || bootstrap_error 'Bash installation did not produce a working bash command.'
}
