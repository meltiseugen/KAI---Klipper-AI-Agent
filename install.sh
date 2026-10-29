#!/bin/sh

if [ -z "${KLIPPERAI_INSTALL_BASH_REEXEC:-}" ]; then
  bootstrap_dir="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)/deployment/installer"
  . "$bootstrap_dir/bootstrap.sh"
  . "$bootstrap_dir/entware.sh"
  case "${1:-}" in
    -h|--help)
      printf '%s\n' 'Usage: sh install.sh [--check|--help]' \
        'Automatically detect the host and install missing application prerequisites.' \
        'Then configure KlipperAI, its service, and optional Mainsail/OctoEverywhere access.' \
        '--help and --check do not install packages or change the host.'
      exit 0 ;;
    --check)
      bootstrap_opt_path
      bootstrap_command_path bash >/dev/null || { bootstrap_error 'Bash is required for syntax checks; no packages were installed.'; exit 127; } ;;
    '') bootstrap_bash || exit 1 ;;
    *) printf 'Unknown option: %s\n' "$1" >&2; exit 2 ;;
  esac
  KLIPPERAI_INSTALL_BASH_REEXEC=1
  export KLIPPERAI_INSTALL_BASH_REEXEC
  exec bash "$0" "$@"
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
