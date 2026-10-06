#!/bin/sh

if [ -z "${KLIPPERAI_INSTALL_BASH_REEXEC:-}" ]; then
  if command -v bash >/dev/null 2>&1; then
    KLIPPERAI_INSTALL_BASH_REEXEC=1
    export KLIPPERAI_INSTALL_BASH_REEXEC
    exec bash "$0" "$@"
  fi

  if command -v apt-get >/dev/null 2>&1; then
    bash_install_hint='apt-get update && apt-get install -y bash'
  elif command -v opkg >/dev/null 2>&1; then
    bash_install_hint='opkg update && opkg install bash'
  elif command -v apk >/dev/null 2>&1; then
    bash_install_hint='apk add bash'
  else
    bash_install_hint='no supported package manager was found; install Bash manually or use a normal Klipper host'
  fi

  printf '%s\n' \
    '[KlipperAI] error: this installer requires Bash, but bash was not found.' \
    '[KlipperAI] Install Bash on the printer host, then rerun:' \
    '[KlipperAI]   chmod +x install.sh' \
    '[KlipperAI]   ./install.sh' \
    '[KlipperAI]' \
    '[KlipperAI] Suggested Bash install command for this host:' \
    "[KlipperAI]   $bash_install_hint" \
    '[KlipperAI]' \
    '[KlipperAI] BusyBox/OpenWrt-style images may not provide apt or systemd.' \
    '[KlipperAI] This installer expects a normal Klipper host with Bash, Python 3.10+, systemd, and nginx.' >&2
  exit 127
fi

set -euo pipefail

PROJECT_NAME="KlipperAI"
SERVICE_NAME="klipperai-agent"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TIMESTAMP="$(date +%Y%m%d%H%M%S)"
MIN_PYTHON_VERSION="3.10"
PYTHON_BIN=""
PYTHON_VENV_MODULE=""


INSTALLER_DIR="$SCRIPT_DIR/deployment/installer"
case "${1:-}" in
  -h|--help)
    printf '%s\n' 'Usage: sh install.sh [--check|--help]' \
      'Interactive Linux service setup with optional Mainsail and OctoEverywhere access.' \
      'Printer configuration and Klipper macros are never installed or edited.' \
      '--check validates installer scripts without changing the host.'
    exit 0 ;;
  --check)
    while IFS= read -r module; do bash -n "$INSTALLER_DIR/$module.sh"; done < "$INSTALLER_DIR/modules.txt"
    printf '%s\n' 'Installer syntax is valid.'
    exit 0 ;;
  '') ;;
  *) printf 'Unknown option: %s\n' "$1" >&2; exit 2 ;;
esac

while IFS= read -r module; do
  source "$INSTALLER_DIR/$module.sh"
done < "$INSTALLER_DIR/modules.txt"

main() {
  preflight
  configure_paths
  configure_options
  install_python_package
  install_service_configuration
  install_access_integrations
  print_next_steps
}

main "$@"
