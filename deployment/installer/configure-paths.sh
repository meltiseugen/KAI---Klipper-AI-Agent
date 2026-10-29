#!/usr/bin/env bash
# Sourced by install.sh; no work is performed on import.

configure_paths() {
  DEFAULT_INSTALL_USER="$(detect_default_install_user)"
  [[ "${KLIPPERAI_SERVICE_MANAGER:-systemd}" != appliance ]] || DEFAULT_INSTALL_USER=root
  INSTALL_USER="$(prompt_default "Linux user that should run the KlipperAI service" "$DEFAULT_INSTALL_USER")"
  id "$INSTALL_USER" >/dev/null 2>&1 || die "User '$INSTALL_USER' does not exist."
  if [[ "${KLIPPERAI_SERVICE_MANAGER:-systemd}" == appliance ]]; then
    [[ "$(id -u "$INSTALL_USER")" -eq 0 ]] || die "The native appliance service uses the host root account."
  else
    [[ "$(id -u "$INSTALL_USER")" -ne 0 ]] || die "Secure installation requires an unprivileged service account with read access to the printer evidence."
  fi

  INSTALL_HOME="$(home_for_user "$INSTALL_USER")"
  [[ -n "$INSTALL_HOME" ]] || die "Could not determine the home directory for '$INSTALL_USER'."
  INSTALL_GROUP="$(group_for_user "$INSTALL_USER")"

  STANDARD_INSTALL_DIR="$INSTALL_HOME/KlipperAI"
  if [[ "${KLIPPERAI_SERVICE_MANAGER:-systemd}" == appliance ]]; then
    STANDARD_INSTALL_DIR="${SCRIPT_DIR:-$STANDARD_INSTALL_DIR}"
  fi
  INSTALL_DIR="$(prompt_default "Project checkout path to install from" "$STANDARD_INSTALL_DIR")"
  ensure_no_spaces "$INSTALL_DIR" "Project checkout path"
  [[ -f "$INSTALL_DIR/pyproject.toml" ]] || die "No pyproject.toml found in $INSTALL_DIR."
  [[ -e "$INSTALL_DIR/.git" ]] || die "$INSTALL_DIR is not a git checkout. Clone the repository before running install.sh."
  run_as_user test -r "$INSTALL_DIR/pyproject.toml" || die "User '$INSTALL_USER' cannot read $INSTALL_DIR."
  run_as_user test -w "$INSTALL_DIR" || die "User '$INSTALL_USER' must be able to write to $INSTALL_DIR."

  DEFAULT_PRINTER_DATA_ROOT="$(detect_printer_data_root "$INSTALL_HOME")"
  KLIPPERAI_PRINTER_DATA_ROOT="$(prompt_default "Printer data root" "$DEFAULT_PRINTER_DATA_ROOT")"
  ensure_no_spaces "$KLIPPERAI_PRINTER_DATA_ROOT" "Printer data root"
  KLIPPERAI_MAINSAIL_CONFIG_DIR="$(prompt_default "Mainsail config directory" "$KLIPPERAI_PRINTER_DATA_ROOT/config")"
  ensure_no_spaces "$KLIPPERAI_MAINSAIL_CONFIG_DIR" "Mainsail config directory"
  KLIPPERAI_MANAGED_CONFIG_DIR_NAME="klipperai"
  KLIPPERAI_MANAGED_CONFIG_DIR_PATH="$KLIPPERAI_MAINSAIL_CONFIG_DIR/$KLIPPERAI_MANAGED_CONFIG_DIR_NAME"
  KLIPPERAI_CFG_PATH="$KLIPPERAI_MANAGED_CONFIG_DIR_PATH/klipperai.cfg"
  KLIPPERAI_LEGACY_CFG_PATH="$KLIPPERAI_MAINSAIL_CONFIG_DIR/klipperai.cfg"
  KLIPPERAI_MOONRAKER_CONFIG_PATH="$(detect_moonraker_config_path "$INSTALL_HOME" "$KLIPPERAI_MAINSAIL_CONFIG_DIR")"
  [[ -f "$KLIPPERAI_MOONRAKER_CONFIG_PATH" ]] || die "Moonraker config file not found: $KLIPPERAI_MOONRAKER_CONFIG_PATH"
  KLIPPERAI_MOONRAKER_CONFIG_DIR="${KLIPPERAI_MOONRAKER_CONFIG_PATH%/*}"
  KLIPPERAI_MOONRAKER_EXTENSION_CFG_PATH="$KLIPPERAI_MANAGED_CONFIG_DIR_PATH/klipperai-moonraker.cfg"
  KLIPPERAI_LEGACY_MOONRAKER_EXTENSION_CFG_PATH="$KLIPPERAI_MOONRAKER_CONFIG_DIR/klipperai-moonraker.cfg"
  KLIPPERAI_MOONRAKER_ALLOWED_SERVICES_PATH="$KLIPPERAI_PRINTER_DATA_ROOT/moonraker.asvc"
  KLIPPERAI_GIT_ORIGIN="$(detect_git_origin)"
  KLIPPERAI_GIT_PRIMARY_BRANCH="$(detect_git_primary_branch)"

  KLIPPERAI_MOONRAKER_URL="$(prompt_default "Moonraker URL" "http://127.0.0.1:7125")"
  KLIPPERAI_ROOT_PATH="$(normalize_root_path "$(prompt_default "Reverse-proxy root path" "/klipperai")")"
  KLIPPERAI_PORT="$(prompt_default "Local KlipperAI bind port" "8811")"
  ensure_numeric_port "$KLIPPERAI_PORT"
  local default_data_dir=/var/lib/klipperai
  if [[ "${KLIPPERAI_SERVICE_MANAGER:-systemd}" == appliance ]]; then
    default_data_dir=/usr/data/klipperai-data
  fi
  KLIPPERAI_DATA_DIR="$(prompt_default "Local KlipperAI data directory" "$default_data_dir")"
  ensure_no_spaces "$KLIPPERAI_DATA_DIR" "Local data directory"
  KLIPPERAI_CHECKPOINT_DB="${KLIPPERAI_DATA_DIR}/checkpoints.sqlite"
  KLIPPERAI_COLLECT_HOST_LOGS="true"
  KLIPPERAI_LOGS_DIR_PATH="${KLIPPERAI_PRINTER_DATA_ROOT}/logs"
  KLIPPERAI_AGENT_LOG_FILE_NAME="klipperai.log"
  KLIPPERAI_AGENT_LOG_LEVEL="INFO"
  KLIPPERAI_LOG_TAIL_LINES_DEFAULT="100"
  KLIPPERAI_COLLECT_SYSTEMD_DIAGNOSTICS="true"
  if [[ "${KLIPPERAI_SERVICE_MANAGER:-systemd}" == appliance ]]; then
    KLIPPERAI_COLLECT_SYSTEMD_DIAGNOSTICS=false
  fi
  KLIPPERAI_MOONRAKER_SERVICE_NAME="moonraker.service"
  KLIPPERAI_KLIPPER_SERVICE_NAME="klipper.service"
  KLIPPERAI_JOURNAL_LINES="200"
  KLIPPERAI_SYSTEM_STATUS_ARTIFACT_CHAR_LIMIT="6000"
  KLIPPERAI_JOURNAL_ARTIFACT_CHAR_LIMIT="16000"
  KLIPPERAI_SYSTEM_COMMAND_TIMEOUT_SECONDS="6"
  KLIPPERAI_OE_ROOT="$(detect_octoeverywhere_root "$INSTALL_HOME" || true)"
  KLIPPERAI_OE_SERVICE_NAME="$(detect_octoeverywhere_service_name || true)"
  INSTALL_OCTOEVERYWHERE_PATCH="no"
  INSTALL_OCTOEVERYWHERE_AUTO_REAPPLY="no"
}
