#!/usr/bin/env bash
# Sourced by install.sh; no work is performed on import.

configure_paths() {
  DEFAULT_INSTALL_USER="$(detect_default_install_user)"
  [[ "${KAI_SERVICE_MANAGER:-systemd}" != appliance ]] || DEFAULT_INSTALL_USER=root
  INSTALL_USER="$(prompt_default "Linux user that should run the KAI service" "$DEFAULT_INSTALL_USER")"
  id "$INSTALL_USER" >/dev/null 2>&1 || die "User '$INSTALL_USER' does not exist."
  if [[ "${KAI_SERVICE_MANAGER:-systemd}" == appliance ]]; then
    [[ "$(id -u "$INSTALL_USER")" -eq 0 ]] || die "The native appliance service uses the host root account."
  else
    [[ "$(id -u "$INSTALL_USER")" -ne 0 ]] || die "Secure installation requires an unprivileged service account with read access to the printer evidence."
  fi

  INSTALL_HOME="$(home_for_user "$INSTALL_USER")"
  [[ -n "$INSTALL_HOME" ]] || die "Could not determine the home directory for '$INSTALL_USER'."
  INSTALL_GROUP="$(group_for_user "$INSTALL_USER")"

  STANDARD_INSTALL_DIR="$INSTALL_HOME/KAI"
  if [[ "${KAI_SERVICE_MANAGER:-systemd}" == appliance ]]; then
    STANDARD_INSTALL_DIR="${SCRIPT_DIR:-$STANDARD_INSTALL_DIR}"
  fi
  INSTALL_DIR="$(prompt_default "Project checkout path to install from" "$STANDARD_INSTALL_DIR")"
  ensure_no_spaces "$INSTALL_DIR" "Project checkout path"
  [[ -f "$INSTALL_DIR/pyproject.toml" ]] || die "No pyproject.toml found in $INSTALL_DIR."
  [[ -e "$INSTALL_DIR/.git" ]] || die "$INSTALL_DIR is not a git checkout. Clone the repository before running install.sh."
  run_as_user test -r "$INSTALL_DIR/pyproject.toml" || die "User '$INSTALL_USER' cannot read $INSTALL_DIR."
  run_as_user test -w "$INSTALL_DIR" || die "User '$INSTALL_USER' must be able to write to $INSTALL_DIR."

  DEFAULT_PRINTER_DATA_ROOT="$(detect_printer_data_root "$INSTALL_HOME")"
  KAI_PRINTER_DATA_ROOT="$(prompt_default "Printer data root" "$DEFAULT_PRINTER_DATA_ROOT")"
  ensure_no_spaces "$KAI_PRINTER_DATA_ROOT" "Printer data root"
  KAI_MAINSAIL_CONFIG_DIR="$(prompt_default "Mainsail config directory" "$KAI_PRINTER_DATA_ROOT/config")"
  ensure_no_spaces "$KAI_MAINSAIL_CONFIG_DIR" "Mainsail config directory"
  KAI_MANAGED_CONFIG_DIR_NAME="kai"
  KAI_MANAGED_CONFIG_DIR_PATH="$KAI_MAINSAIL_CONFIG_DIR/$KAI_MANAGED_CONFIG_DIR_NAME"
  KAI_CFG_PATH="$KAI_MANAGED_CONFIG_DIR_PATH/kai.cfg"
  KAI_LEGACY_CFG_PATH="$KAI_MAINSAIL_CONFIG_DIR/kai.cfg"
  KAI_MOONRAKER_CONFIG_PATH="$(detect_moonraker_config_path "$INSTALL_HOME" "$KAI_MAINSAIL_CONFIG_DIR")"
  [[ -f "$KAI_MOONRAKER_CONFIG_PATH" ]] || die "Moonraker config file not found: $KAI_MOONRAKER_CONFIG_PATH"
  KAI_MOONRAKER_CONFIG_DIR="${KAI_MOONRAKER_CONFIG_PATH%/*}"
  KAI_MOONRAKER_EXTENSION_CFG_PATH="$KAI_MANAGED_CONFIG_DIR_PATH/kai-moonraker.cfg"
  KAI_LEGACY_MOONRAKER_EXTENSION_CFG_PATH="$KAI_MOONRAKER_CONFIG_DIR/kai-moonraker.cfg"
  KAI_MOONRAKER_ALLOWED_SERVICES_PATH="$KAI_PRINTER_DATA_ROOT/moonraker.asvc"
  KAI_GIT_ORIGIN="$(detect_git_origin)"
  KAI_GIT_PRIMARY_BRANCH="$(detect_git_primary_branch)"

  KAI_MOONRAKER_URL="$(prompt_default "Moonraker URL" "http://127.0.0.1:7125")"
  KAI_ROOT_PATH="$(normalize_root_path "$(prompt_default "Reverse-proxy root path" "/kai")")"
  KAI_PORT="$(prompt_default "Local KAI bind port" "8811")"
  ensure_numeric_port "$KAI_PORT"
  local default_data_dir=/var/lib/kai
  if [[ "${KAI_SERVICE_MANAGER:-systemd}" == appliance ]]; then
    default_data_dir=/usr/data/kai-data
  fi
  KAI_DATA_DIR="$(prompt_default "Local KAI data directory" "$default_data_dir")"
  ensure_no_spaces "$KAI_DATA_DIR" "Local data directory"
  KAI_CHECKPOINT_DB="${KAI_DATA_DIR}/checkpoints.sqlite"
  KAI_COLLECT_HOST_LOGS="true"
  KAI_LOGS_DIR_PATH="${KAI_PRINTER_DATA_ROOT}/logs"
  KAI_AGENT_LOG_FILE_NAME="kai.log"
  KAI_AGENT_LOG_LEVEL="INFO"
  KAI_LOG_TAIL_LINES_DEFAULT="100"
  KAI_COLLECT_SYSTEMD_DIAGNOSTICS="true"
  if [[ "${KAI_SERVICE_MANAGER:-systemd}" == appliance ]]; then
    KAI_COLLECT_SYSTEMD_DIAGNOSTICS=false
  fi
  KAI_MOONRAKER_SERVICE_NAME="moonraker.service"
  KAI_KLIPPER_SERVICE_NAME="klipper.service"
  KAI_JOURNAL_LINES="200"
  KAI_SYSTEM_STATUS_ARTIFACT_CHAR_LIMIT="6000"
  KAI_JOURNAL_ARTIFACT_CHAR_LIMIT="16000"
  KAI_SYSTEM_COMMAND_TIMEOUT_SECONDS="6"
  KAI_OE_ROOT="$(detect_octoeverywhere_root "$INSTALL_HOME" || true)"
  KAI_OE_SERVICE_NAME="$(detect_octoeverywhere_service_name || true)"
  INSTALL_OCTOEVERYWHERE_PATCH="no"
  INSTALL_OCTOEVERYWHERE_AUTO_REAPPLY="no"
}
