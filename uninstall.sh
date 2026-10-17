#!/usr/bin/env bash

set -euo pipefail

PROJECT_NAME="KlipperAI"
SERVICE_NAME="klipperai-agent"
TIMESTAMP="$(date +%Y%m%d%H%M%S)"
ENV_FILE="/etc/klipperai/klipperai.env"
SYSTEMD_UNIT_PATH="/etc/systemd/system/${SERVICE_NAME}.service"
NGINX_SNIPPET_PATH="/etc/klipperai/nginx-location.conf"
OE_REAPPLY_RUNNER_PATH="/usr/local/bin/klipperai-octoeverywhere-reapply"
OE_REAPPLY_SERVICE_NAME="klipperai-octoeverywhere-reapply.service"
OE_REAPPLY_TIMER_NAME="klipperai-octoeverywhere-reapply.timer"
OE_REAPPLY_PATH_NAME="klipperai-octoeverywhere-reapply.path"
OE_REAPPLY_SERVICE_PATH="/etc/systemd/system/${OE_REAPPLY_SERVICE_NAME}"
OE_REAPPLY_TIMER_PATH="/etc/systemd/system/${OE_REAPPLY_TIMER_NAME}"
OE_REAPPLY_PATH_PATH="/etc/systemd/system/${OE_REAPPLY_PATH_NAME}"
MAINSAIL_REAPPLY_NAME="klipperai-mainsail-reapply"
MAINSAIL_REAPPLY_UNIT_DIR="${KLIPPERAI_SYSTEMD_DIR:-/etc/systemd/system}"

log() {
  printf '[%s] %s\n' "$PROJECT_NAME" "$*"
}

warn() {
  printf '[%s] warning: %s\n' "$PROJECT_NAME" "$*" >&2
}

die() {
  printf '[%s] error: %s\n' "$PROJECT_NAME" "$*" >&2
  exit 1
}

confirm() {
  local prompt="$1"
  local default="${2:-N}"
  local suffix="[y/N]"
  local reply=""

  if [[ "$default" == "Y" ]]; then
    suffix="[Y/n]"
  fi

  read -r -p "$prompt $suffix " reply
  reply="${reply:-$default}"
  case "${reply,,}" in
    y|yes) return 0 ;;
    n|no) return 1 ;;
    *) warn "Please answer yes or no."; confirm "$prompt" "$default"; return $? ;;
  esac
}

prompt_default() {
  local prompt="$1"
  local default="$2"
  local reply=""
  read -r -p "$prompt [$default]: " reply
  printf '%s' "${reply:-$default}"
}

trim_whitespace() {
  local value="$1"
  value="${value#"${value%%[![:space:]]*}"}"
  value="${value%"${value##*[![:space:]]}"}"
  printf '%s' "$value"
}

require_linux() {
  [[ "$(uname -s)" == "Linux" ]] || die "This uninstaller only supports Linux hosts."
}

require_cmd() {
  local command_name="$1"
  command -v "$command_name" >/dev/null 2>&1 || die "Required command not found: $command_name"
}

home_for_user() {
  if command -v getent >/dev/null 2>&1; then
    getent passwd "$1" | cut -d: -f6
    return
  fi

  awk -F: -v target="$1" '$1 == target { print $6; exit }' /etc/passwd
}

run_root() {
  if [[ "${EUID}" -eq 0 ]]; then
    "$@"
  else
    command -v sudo >/dev/null 2>&1 || die "sudo is required for uninstall."
    sudo "$@"
  fi
}

run_as_user() {
  local target_user="$1"
  shift

  if [[ "$(id -un)" == "$target_user" ]]; then
    "$@"
    return
  fi

  if [[ "${EUID}" -eq 0 ]] && command -v runuser >/dev/null 2>&1; then
    runuser -u "$target_user" -- "$@"
    return
  fi

  if command -v sudo >/dev/null 2>&1; then
    sudo -u "$target_user" -H "$@"
    return
  fi

  die "Unable to switch to user '$target_user'."
}

backup_file() {
  local path="$1"
  if [[ -e "$path" ]]; then
    run_root cp "$path" "${path}.bak.${TIMESTAMP}"
    log "Backed up $path to ${path}.bak.${TIMESTAMP}"
  fi
}

extract_env_value() {
  local path="$1"
  local key="$2"
  [[ -f "$path" ]] || return 1

  local line=""
  line="$(grep -E "^${key}=" "$path" | tail -n1 || true)"
  [[ -n "$line" ]] || return 1

  line="${line#*=}"
  if [[ "${line:0:1}" == '"' && "${line: -1}" == '"' ]]; then
    line="${line:1:${#line}-2}"
  fi
  line="${line//\\\"/\"}"
  line="${line//\\\\/\\}"
  printf '%s' "$line"
}

get_cfg_value() {
  local path="$1"
  local section="$2"
  local key="$3"
  [[ -f "$path" ]] || return 1

  awk -v target_section="$section" -v target_key="$key" '
    function trim(value) {
      gsub(/^[ \t]+|[ \t]+$/, "", value)
      return value
    }
    /^\[[^]]+\]/ {
      current = $0
      sub(/^\[/, "", current)
      sub(/\]$/, "", current)
      current = trim(current)
      next
    }
    /^[ \t]*[A-Za-z0-9_.-]+[ \t]*[:=]/ {
      if (current != target_section) {
        next
      }
      line = $0
      sub(/^[ \t]*/, "", line)
      key = line
      sub(/[ \t]*[:=].*$/, "", key)
      key = trim(key)
      if (key != target_key) {
        next
      }
      match(line, /[:=]/)
      value = substr(line, RSTART + 1)
      sub(/[ \t]+#.*/, "", value)
      sub(/[ \t]+;.*/, "", value)
      print trim(value)
      exit
    }
  ' "$path"
}

remove_file_if_present() {
  local path="$1"
  if [[ -e "$path" ]]; then
    run_root rm -f -- "$path"
    log "Removed $path"
  fi
}

remove_dir_if_present() {
  local path="$1"
  if [[ -d "$path" ]]; then
    run_root rm -rf -- "$path"
    log "Removed $path"
  fi
}

remove_line_from_file() {
  local path="$1"
  local line_to_remove="$2"
  [[ -f "$path" ]] || return 0

  if ! grep -Fqx "$line_to_remove" "$path"; then
    return 0
  fi

  local temp_file
  temp_file="$(mktemp)"
  local mode
  local owner
  local group
  mode="$(stat -c '%a' "$path")"
  owner="$(stat -c '%u' "$path")"
  group="$(stat -c '%g' "$path")"
  grep -Fvx "$line_to_remove" "$path" >"$temp_file" || true
  backup_file "$path"
  run_root install -o "$owner" -g "$group" -m "$mode" "$temp_file" "$path"
  rm -f "$temp_file"
  log "Updated $path"
}

remove_trimmed_line_from_file() {
  local path="$1"
  local line_to_remove="$2"
  [[ -f "$path" ]] || return 0

  if ! awk -v needle="$line_to_remove" '
    function trim(value) {
      gsub(/^[ \t]+|[ \t]+$/, "", value)
      return value
    }
    {
      if (trim($0) == needle) {
        found = 1
        exit
      }
    }
    END {
      exit(found ? 0 : 1)
    }
  ' "$path"; then
    return 0
  fi

  local temp_file
  temp_file="$(mktemp)"
  local mode
  local owner
  local group
  mode="$(stat -c '%a' "$path")"
  owner="$(stat -c '%u' "$path")"
  group="$(stat -c '%g' "$path")"
  awk -v needle="$line_to_remove" '
    function trim(value) {
      gsub(/^[ \t]+|[ \t]+$/, "", value)
      return value
    }
    {
      if (trim($0) != needle) {
        print $0
      }
    }
  ' "$path" >"$temp_file"
  backup_file "$path"
  run_root install -o "$owner" -g "$group" -m "$mode" "$temp_file" "$path"
  rm -f "$temp_file"
  log "Updated $path"
}

detect_moonraker_config_path() {
  local home_dir="$1"
  local config_dir="$2"
  local candidate=""

  for candidate in \
    "$config_dir/moonraker.conf" \
    "$home_dir/printer_data/config/moonraker.conf" \
    "$home_dir/moonraker.conf"
  do
    if [[ -f "$candidate" ]]; then
      printf '%s' "$candidate"
      return
    fi
  done

  printf '%s' "$config_dir/moonraker.conf"
}

relative_config_include_path() {
  local target_path="$1"
  local source_config_path="$2"

  python3 - "$target_path" "${source_config_path%/*}" <<'PY'
import os
import sys

target = os.path.abspath(sys.argv[1])
source_dir = os.path.abspath(sys.argv[2])
print(os.path.relpath(target, source_dir).replace(os.sep, "/"))
PY
}

build_include_line() {
  local target_path="$1"
  local source_config_path="$2"
  printf '[include %s]' "$(relative_config_include_path "$target_path" "$source_config_path")"
}

detect_nginx_server_block_path() {
  local candidate=""

  for candidate in \
    /etc/nginx/conf.d/mainsail.conf \
    /etc/nginx/sites-enabled/mainsail \
    /etc/nginx/sites-available/mainsail
  do
    if [[ -f "$candidate" ]]; then
      printf '%s' "$candidate"
      return
    fi
  done

  printf '%s' "/etc/nginx/conf.d/mainsail.conf"
}

reload_nginx() {
  run_root nginx -t
  run_root systemctl reload nginx
}

remove_mainsail_auto_reapply() {
  local suffix
  local installed=no
  for suffix in timer path service; do
    [[ ! -f "$MAINSAIL_REAPPLY_UNIT_DIR/${MAINSAIL_REAPPLY_NAME}.${suffix}" ]] || installed=yes
  done
  [[ "$installed" == yes ]] || return 0
  run_root systemctl disable --now "${MAINSAIL_REAPPLY_NAME}.timer" "${MAINSAIL_REAPPLY_NAME}.path"
  run_root systemctl stop "${MAINSAIL_REAPPLY_NAME}.service"
  for suffix in timer path service; do
    remove_file_if_present "$MAINSAIL_REAPPLY_UNIT_DIR/${MAINSAIL_REAPPLY_NAME}.${suffix}"
  done
  run_root systemctl daemon-reload
}

print_summary() {
  cat <<EOF

Uninstall summary
-----------------
Service unit:          $SYSTEMD_UNIT_PATH
Env file:              $ENV_FILE
KlipperAI cfg:          ${KLIPPERAI_CFG_PATH:-<not found>}
Moonraker config:      ${KLIPPERAI_MOONRAKER_CONFIG_PATH:-<not found>}
Moonraker include:     ${KLIPPERAI_MOONRAKER_EXTENSION_CFG_PATH:-<not found>}
Allowed services file: ${KLIPPERAI_MOONRAKER_ALLOWED_SERVICES_PATH:-<not found>}
Mainsail config dir:   ${KLIPPERAI_MAINSAIL_CONFIG_DIR:-<not found>}
Managed config dir:    ${KLIPPERAI_MANAGED_CONFIG_DIR_PATH:-<not found>}
Data dir:              ${KLIPPERAI_DATA_DIR:-<not found>}
Project checkout:      ${KLIPPERAI_PROJECT_CHECKOUT_PATH:-<not found>}
nginx server block:    ${KLIPPERAI_NGINX_SERVER_BLOCK_PATH:-<not found>}
Remove nav entry:      $REMOVE_MAINSAIL_NAV
Mainsail repair units: removed automatically when installed
Remove nginx include:  $REMOVE_NGINX_INCLUDE
Remove data dir:       $REMOVE_DATA_DIR
Remove nginx snippet:  $REMOVE_NGINX_SNIPPET
Remove checkout dir:   $REMOVE_CHECKOUT_DIR
Remove update macro:   $REMOVE_UPDATE_MACRO_INTEGRATION
Remove OE auto-reapply: $REMOVE_OE_REAPPLY_INTEGRATION

EOF
}

main() {
  require_linux
  require_cmd awk
  require_cmd grep
  require_cmd install
  require_cmd python3
  require_cmd stat
  require_cmd systemctl

  log "Preparing uninstall."

  KLIPPERAI_CFG_PATH="$(extract_env_value "$ENV_FILE" "KLIPPERAI_CONFIG_FILE" || true)"
  if [[ -z "${KLIPPERAI_CFG_PATH:-}" ]]; then
    KLIPPERAI_CFG_PATH="$(prompt_default "Path to klipperai.cfg" "/home/pi/printer_data/config/klipperai/klipperai.cfg")"
  fi

  KLIPPERAI_MAINSAIL_CONFIG_DIR="$(get_cfg_value "$KLIPPERAI_CFG_PATH" "install" "mainsail_config_dir" || true)"
  KLIPPERAI_PRINTER_DATA_ROOT="$(get_cfg_value "$KLIPPERAI_CFG_PATH" "install" "printer_data_root" || true)"
  KLIPPERAI_PROJECT_CHECKOUT_PATH="$(extract_env_value "$ENV_FILE" "KLIPPERAI_PROJECT_CHECKOUT_PATH" || true)"
  if [[ -z "${KLIPPERAI_PROJECT_CHECKOUT_PATH:-}" ]]; then
    KLIPPERAI_PROJECT_CHECKOUT_PATH="$(get_cfg_value "$KLIPPERAI_CFG_PATH" "install" "project_checkout_path" || true)"
  fi
  KLIPPERAI_SERVICE_USER="$(extract_env_value "$ENV_FILE" "KLIPPERAI_SERVICE_USER" || true)"
  if [[ -z "${KLIPPERAI_SERVICE_USER:-}" ]]; then
    KLIPPERAI_SERVICE_USER="$(get_cfg_value "$KLIPPERAI_CFG_PATH" "install" "service_user" || true)"
  fi
  KLIPPERAI_NGINX_SERVER_BLOCK_PATH="$(extract_env_value "$ENV_FILE" "KLIPPERAI_NGINX_SERVER_BLOCK_PATH" || true)"
  if [[ -z "${KLIPPERAI_NGINX_SERVER_BLOCK_PATH:-}" ]]; then
    KLIPPERAI_NGINX_SERVER_BLOCK_PATH="$(get_cfg_value "$KLIPPERAI_CFG_PATH" "install" "nginx_server_block_path" || true)"
  fi
  KLIPPERAI_DATA_DIR="$(get_cfg_value "$KLIPPERAI_CFG_PATH" "server" "data_dir" || true)"

  if [[ -z "${KLIPPERAI_SERVICE_USER:-}" ]] && [[ -n "${SUDO_USER:-}" ]] && [[ "${SUDO_USER}" != "root" ]]; then
    KLIPPERAI_SERVICE_USER="$SUDO_USER"
  fi
  if [[ -z "${KLIPPERAI_SERVICE_USER:-}" ]]; then
    KLIPPERAI_SERVICE_USER="$(id -un)"
  fi
  KLIPPERAI_SERVICE_HOME="$(home_for_user "$KLIPPERAI_SERVICE_USER" || true)"
  if [[ -z "${KLIPPERAI_SERVICE_HOME:-}" ]]; then
    KLIPPERAI_SERVICE_HOME="/home/${KLIPPERAI_SERVICE_USER}"
  fi

  if [[ -z "${KLIPPERAI_MAINSAIL_CONFIG_DIR:-}" ]] && [[ -n "${KLIPPERAI_PRINTER_DATA_ROOT:-}" ]]; then
    KLIPPERAI_MAINSAIL_CONFIG_DIR="${KLIPPERAI_PRINTER_DATA_ROOT%/}/config"
  fi
  if [[ -z "${KLIPPERAI_PRINTER_DATA_ROOT:-}" ]]; then
    KLIPPERAI_PRINTER_DATA_ROOT="${KLIPPERAI_SERVICE_HOME%/}/printer_data"
  fi
  if [[ -z "${KLIPPERAI_PROJECT_CHECKOUT_PATH:-}" ]]; then
    KLIPPERAI_PROJECT_CHECKOUT_PATH="${KLIPPERAI_SERVICE_HOME%/}/KlipperAI"
  fi
  if [[ -z "${KLIPPERAI_DATA_DIR:-}" ]]; then
    KLIPPERAI_DATA_DIR="/var/lib/klipperai"
  fi
  if [[ -z "${KLIPPERAI_MAINSAIL_CONFIG_DIR:-}" ]]; then
    KLIPPERAI_MAINSAIL_CONFIG_DIR="${KLIPPERAI_SERVICE_HOME%/}/printer_data/config"
  fi
  KLIPPERAI_MANAGED_CONFIG_DIR_NAME="$(extract_env_value "$ENV_FILE" "KLIPPERAI_MANAGED_CONFIG_DIR_NAME" || true)"
  if [[ -z "${KLIPPERAI_MANAGED_CONFIG_DIR_NAME:-}" ]]; then
    KLIPPERAI_MANAGED_CONFIG_DIR_NAME="klipperai"
  fi
  KLIPPERAI_MANAGED_CONFIG_DIR_PATH="${KLIPPERAI_CFG_PATH%/*}"
  if [[ "$KLIPPERAI_MANAGED_CONFIG_DIR_PATH" == "$KLIPPERAI_MAINSAIL_CONFIG_DIR" ]]; then
    KLIPPERAI_MANAGED_CONFIG_DIR_PATH="${KLIPPERAI_MAINSAIL_CONFIG_DIR%/}/$KLIPPERAI_MANAGED_CONFIG_DIR_NAME"
  fi
  if [[ -z "${KLIPPERAI_NGINX_SERVER_BLOCK_PATH:-}" ]]; then
    KLIPPERAI_NGINX_SERVER_BLOCK_PATH="$(detect_nginx_server_block_path)"
  fi

  KLIPPERAI_MOONRAKER_CONFIG_PATH="$(detect_moonraker_config_path "$KLIPPERAI_SERVICE_HOME" "$KLIPPERAI_MAINSAIL_CONFIG_DIR")"
  KLIPPERAI_MOONRAKER_CONFIG_DIR="${KLIPPERAI_MOONRAKER_CONFIG_PATH%/*}"
  KLIPPERAI_MOONRAKER_EXTENSION_CFG_PATH="${KLIPPERAI_MANAGED_CONFIG_DIR_PATH}/klipperai-moonraker.cfg"
  KLIPPERAI_MOONRAKER_ALLOWED_SERVICES_PATH="${KLIPPERAI_PRINTER_DATA_ROOT%/}/moonraker.asvc"
  KLIPPERAI_MAINSAIL_NAV_HREF="$(get_cfg_value "$KLIPPERAI_CFG_PATH" "server" "root_path" || true)"
  KLIPPERAI_MAINSAIL_NAV_HREF="${KLIPPERAI_MAINSAIL_NAV_HREF:-/klipperai}"
  KLIPPERAI_MAINSAIL_NAV_HREF="${KLIPPERAI_MAINSAIL_NAV_HREF%/}/"
  KLIPPERAI_UPDATE_RUNNER_PATH="/usr/local/bin/klipperai-self-update"
  KLIPPERAI_UPDATE_SUDOERS_PATH="/etc/sudoers.d/klipperai-self-update"
  KLIPPERAI_UPDATE_MACRO_CFG_PATH="${KLIPPERAI_MANAGED_CONFIG_DIR_PATH}/klipperai-macros.cfg"
  if [[ ! -f "$KLIPPERAI_MOONRAKER_EXTENSION_CFG_PATH" && -f "${KLIPPERAI_MOONRAKER_CONFIG_DIR}/klipperai-moonraker.cfg" ]]; then
    KLIPPERAI_MOONRAKER_EXTENSION_CFG_PATH="${KLIPPERAI_MOONRAKER_CONFIG_DIR}/klipperai-moonraker.cfg"
  fi
  if [[ ! -f "$KLIPPERAI_UPDATE_MACRO_CFG_PATH" && -f "${KLIPPERAI_MAINSAIL_CONFIG_DIR%/}/klipperai-update-macro.cfg" ]]; then
    KLIPPERAI_UPDATE_MACRO_CFG_PATH="${KLIPPERAI_MAINSAIL_CONFIG_DIR%/}/klipperai-update-macro.cfg"
  fi
  KLIPPERAI_KLIPPER_ROOT_CONFIG_VALUE="$(get_cfg_value "$KLIPPERAI_CFG_PATH" "config_context" "root_config_file" || true)"
  KLIPPERAI_KLIPPER_ROOT_CONFIG_VALUE="$(trim_whitespace "$KLIPPERAI_KLIPPER_ROOT_CONFIG_VALUE")"
  if [[ -z "${KLIPPERAI_KLIPPER_ROOT_CONFIG_VALUE:-}" ]]; then
    KLIPPERAI_KLIPPER_ROOT_CONFIG_PATH="${KLIPPERAI_MAINSAIL_CONFIG_DIR%/}/printer.cfg"
  elif [[ "$KLIPPERAI_KLIPPER_ROOT_CONFIG_VALUE" == /* ]]; then
    KLIPPERAI_KLIPPER_ROOT_CONFIG_PATH="$KLIPPERAI_KLIPPER_ROOT_CONFIG_VALUE"
  else
    KLIPPERAI_KLIPPER_ROOT_CONFIG_PATH="${KLIPPERAI_MAINSAIL_CONFIG_DIR%/}/$KLIPPERAI_KLIPPER_ROOT_CONFIG_VALUE"
  fi

  if confirm "Remove the Mainsail custom-navigation entry?" "Y"; then
    REMOVE_MAINSAIL_NAV="yes"
  else
    REMOVE_MAINSAIL_NAV="no"
  fi

  if [[ -f "${KLIPPERAI_NGINX_SERVER_BLOCK_PATH:-}" ]] && confirm "Remove the KlipperAI nginx include line from ${KLIPPERAI_NGINX_SERVER_BLOCK_PATH}?" "Y"; then
    REMOVE_NGINX_INCLUDE="yes"
  else
    REMOVE_NGINX_INCLUDE="no"
  fi

  if confirm "Remove the KlipperAI data directory (${KLIPPERAI_DATA_DIR})?" "N"; then
    REMOVE_DATA_DIR="yes"
  else
    REMOVE_DATA_DIR="no"
  fi

  if confirm "Delete the nginx snippet file (${NGINX_SNIPPET_PATH}) now?" "N"; then
    REMOVE_NGINX_SNIPPET="yes"
  else
    REMOVE_NGINX_SNIPPET="no"
  fi

  if [[ "$REMOVE_NGINX_SNIPPET" == "yes" && "$REMOVE_NGINX_INCLUDE" != "yes" ]]; then
    die "Refusing to delete ${NGINX_SNIPPET_PATH} while keeping its nginx include line. Remove the include line first or keep the snippet file."
  fi

  if confirm "Delete the project checkout directory (${KLIPPERAI_PROJECT_CHECKOUT_PATH})?" "N"; then
    REMOVE_CHECKOUT_DIR="yes"
  else
    REMOVE_CHECKOUT_DIR="no"
  fi

  if [[ -f "$KLIPPERAI_UPDATE_MACRO_CFG_PATH" || -f "$KLIPPERAI_UPDATE_RUNNER_PATH" || -f "$KLIPPERAI_UPDATE_SUDOERS_PATH" ]]; then
    if confirm "Remove the optional UPDATE_KLIPPERAI macro integration?" "Y"; then
      REMOVE_UPDATE_MACRO_INTEGRATION="yes"
    else
      REMOVE_UPDATE_MACRO_INTEGRATION="no"
    fi
  else
    REMOVE_UPDATE_MACRO_INTEGRATION="no"
  fi

  if [[ -f "$OE_REAPPLY_RUNNER_PATH" || -f "$OE_REAPPLY_SERVICE_PATH" || -f "$OE_REAPPLY_TIMER_PATH" || -f "$OE_REAPPLY_PATH_PATH" ]]; then
    if confirm "Remove the OctoEverywhere patch auto-reapply timer?" "Y"; then
      REMOVE_OE_REAPPLY_INTEGRATION="yes"
    else
      REMOVE_OE_REAPPLY_INTEGRATION="no"
    fi
  else
    REMOVE_OE_REAPPLY_INTEGRATION="no"
  fi

  print_summary
  confirm "Proceed with uninstall?" "N" || die "Uninstall cancelled."

  if systemctl list-unit-files "$SERVICE_NAME" >/dev/null 2>&1; then
    log "Stopping and disabling ${SERVICE_NAME}."
    run_root systemctl disable --now "$SERVICE_NAME" || warn "Could not fully disable ${SERVICE_NAME}."
  fi

  remove_file_if_present "$SYSTEMD_UNIT_PATH"
  run_root systemctl daemon-reload

  # Stop navigation repair before removing its link or the checkout it executes.
  remove_mainsail_auto_reapply

  if [[ "$REMOVE_OE_REAPPLY_INTEGRATION" == "yes" ]]; then
    log "Stopping and disabling ${OE_REAPPLY_TIMER_NAME}."
    run_root systemctl disable --now "$OE_REAPPLY_TIMER_NAME" || warn "Could not fully disable ${OE_REAPPLY_TIMER_NAME}."
    run_root systemctl disable --now "$OE_REAPPLY_PATH_NAME" || warn "Could not fully disable ${OE_REAPPLY_PATH_NAME}."
    run_root systemctl disable --now "$OE_REAPPLY_SERVICE_NAME" || true
    remove_file_if_present "$OE_REAPPLY_TIMER_PATH"
    remove_file_if_present "$OE_REAPPLY_PATH_PATH"
    remove_file_if_present "$OE_REAPPLY_SERVICE_PATH"
    remove_file_if_present "$OE_REAPPLY_RUNNER_PATH"
    run_root systemctl daemon-reload
  fi

  if [[ "$REMOVE_MAINSAIL_NAV" == "yes" ]] && [[ -d "$KLIPPERAI_MAINSAIL_CONFIG_DIR" ]]; then
    if command -v python3 >/dev/null 2>&1 && [[ -f "$KLIPPERAI_PROJECT_CHECKOUT_PATH/integrations/mainsail/uninstall-custom-nav.sh" ]]; then
      if id "$KLIPPERAI_SERVICE_USER" >/dev/null 2>&1; then
        run_as_user "$KLIPPERAI_SERVICE_USER" bash "$KLIPPERAI_PROJECT_CHECKOUT_PATH/integrations/mainsail/uninstall-custom-nav.sh" \
          --config-dir "$KLIPPERAI_MAINSAIL_CONFIG_DIR" \
          --href "$KLIPPERAI_MAINSAIL_NAV_HREF" \
          --title "KlipperAI"
      else
        warn "Skipping Mainsail nav removal because the service user '$KLIPPERAI_SERVICE_USER' does not exist."
      fi
    else
      warn "Skipping Mainsail nav removal because python3 or uninstall-custom-nav.sh is unavailable."
    fi
  fi

  if [[ -f "$KLIPPERAI_MOONRAKER_CONFIG_PATH" ]]; then
    remove_line_from_file "$KLIPPERAI_MOONRAKER_CONFIG_PATH" "$(build_include_line "$KLIPPERAI_MOONRAKER_EXTENSION_CFG_PATH" "$KLIPPERAI_MOONRAKER_CONFIG_PATH")"
  fi
  remove_file_if_present "$KLIPPERAI_MOONRAKER_EXTENSION_CFG_PATH"
  remove_line_from_file "$KLIPPERAI_MOONRAKER_ALLOWED_SERVICES_PATH" "$SERVICE_NAME"
  remove_file_if_present "$KLIPPERAI_CFG_PATH"
  remove_file_if_present "$ENV_FILE"

  if [[ "$REMOVE_UPDATE_MACRO_INTEGRATION" == "yes" ]]; then
    if [[ -f "$KLIPPERAI_KLIPPER_ROOT_CONFIG_PATH" ]]; then
      remove_line_from_file "$KLIPPERAI_KLIPPER_ROOT_CONFIG_PATH" "$(build_include_line "$KLIPPERAI_UPDATE_MACRO_CFG_PATH" "$KLIPPERAI_KLIPPER_ROOT_CONFIG_PATH")"
    fi
    remove_file_if_present "$KLIPPERAI_UPDATE_MACRO_CFG_PATH"
    remove_file_if_present "$KLIPPERAI_UPDATE_RUNNER_PATH"
    remove_file_if_present "$KLIPPERAI_UPDATE_SUDOERS_PATH"
  fi

  if [[ -n "${KLIPPERAI_MANAGED_CONFIG_DIR_PATH:-}" ]] && [[ -d "$KLIPPERAI_MANAGED_CONFIG_DIR_PATH" ]]; then
    if [[ -z "$(find "$KLIPPERAI_MANAGED_CONFIG_DIR_PATH" -mindepth 1 -maxdepth 1 -print -quit 2>/dev/null)" ]]; then
      remove_dir_if_present "$KLIPPERAI_MANAGED_CONFIG_DIR_PATH"
    fi
  fi

  if [[ "$REMOVE_NGINX_INCLUDE" == "yes" ]]; then
    remove_trimmed_line_from_file "$KLIPPERAI_NGINX_SERVER_BLOCK_PATH" "include ${NGINX_SNIPPET_PATH};"
    log "Testing and reloading nginx."
    reload_nginx
  fi

  if [[ "$REMOVE_NGINX_SNIPPET" == "yes" ]]; then
    remove_file_if_present "$NGINX_SNIPPET_PATH"
  fi

  if [[ "$REMOVE_DATA_DIR" == "yes" ]]; then
    remove_dir_if_present "$KLIPPERAI_DATA_DIR"
  fi

  if [[ "$REMOVE_CHECKOUT_DIR" == "yes" ]]; then
    if [[ -n "$KLIPPERAI_PROJECT_CHECKOUT_PATH" && "$KLIPPERAI_PROJECT_CHECKOUT_PATH" != "/" ]]; then
      cd /
      remove_dir_if_present "$KLIPPERAI_PROJECT_CHECKOUT_PATH"
    else
      warn "Refusing to remove an unsafe checkout path: ${KLIPPERAI_PROJECT_CHECKOUT_PATH:-<empty>}"
    fi
  fi

  cat <<EOF

Uninstall complete
------------------
Removed:
- systemd unit for ${SERVICE_NAME}
- KlipperAI runtime config
- Moonraker include entry and allowed-services entry
- KlipperAI environment file
- optional UPDATE_KLIPPERAI macro artifacts when selected
- optional OctoEverywhere auto-reapply artifacts when selected
- Mainsail navigation auto-reapply units, if installed

Manual follow-up:
1. Restart Moonraker:
   sudo systemctl restart moonraker
2. If you kept the nginx include line or the snippet file, test and reload nginx:
   sudo nginx -t && sudo systemctl reload nginx
3. If you kept the checkout directory, you can remove it later manually.

EOF
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  main "$@"
fi
