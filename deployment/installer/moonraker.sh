#!/usr/bin/env bash
# Sourced by install.sh; no work is performed on import.

write_moonraker_extension_cfg() {
  local temp_file
  temp_file="$(mktemp)"

  cat >"$temp_file" <<EOF
# KlipperAI Moonraker integration
#
# This file is included from moonraker.conf so that KlipperAI appears in
# Moonraker's update manager and can be managed from Mainsail.

[update_manager klipperai-agent]
type: git_repo
channel: dev
path: $INSTALL_DIR
origin: $KLIPPERAI_GIT_ORIGIN
primary_branch: $KLIPPERAI_GIT_PRIMARY_BRANCH
managed_services: klipperai-agent
info_tags:
    desc=KlipperAI
EOF

  run_root install -d -o "$INSTALL_USER" -g "$INSTALL_GROUP" -m 755 "$KLIPPERAI_MANAGED_CONFIG_DIR_PATH"
  backup_file "$KLIPPERAI_MOONRAKER_EXTENSION_CFG_PATH"
  run_root install -o "$INSTALL_USER" -g "$INSTALL_GROUP" -m 664 "$temp_file" "$KLIPPERAI_MOONRAKER_EXTENSION_CFG_PATH"
  rm -f "$temp_file"
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

ensure_moonraker_include() {
  local include_line
  include_line="$(build_include_line "$KLIPPERAI_MOONRAKER_EXTENSION_CFG_PATH" "$KLIPPERAI_MOONRAKER_CONFIG_PATH")"
  local legacy_include_line="[include $(basename "$KLIPPERAI_LEGACY_MOONRAKER_EXTENSION_CFG_PATH")]"

  [[ -f "$KLIPPERAI_MOONRAKER_CONFIG_PATH" ]] || die "Moonraker config file not found: $KLIPPERAI_MOONRAKER_CONFIG_PATH"
  if [[ "$legacy_include_line" != "$include_line" ]]; then
    remove_line_from_file_if_present "$KLIPPERAI_MOONRAKER_CONFIG_PATH" "$legacy_include_line"
  fi
  if grep -Fqx "$include_line" "$KLIPPERAI_MOONRAKER_CONFIG_PATH"; then
    return
  fi

  backup_file "$KLIPPERAI_MOONRAKER_CONFIG_PATH"
  printf '\n%s\n' "$include_line" | run_root tee -a "$KLIPPERAI_MOONRAKER_CONFIG_PATH" >/dev/null
}

ensure_moonraker_allowed_service() {
  if [[ -f "$KLIPPERAI_MOONRAKER_ALLOWED_SERVICES_PATH" ]] && grep -Fqx "$SERVICE_NAME" "$KLIPPERAI_MOONRAKER_ALLOWED_SERVICES_PATH"; then
    return
  fi

  run_root install -d -o "$INSTALL_USER" -g "$INSTALL_GROUP" -m 755 "$KLIPPERAI_PRINTER_DATA_ROOT"
  if [[ -f "$KLIPPERAI_MOONRAKER_ALLOWED_SERVICES_PATH" ]]; then
    backup_file "$KLIPPERAI_MOONRAKER_ALLOWED_SERVICES_PATH"
    printf '%s\n' "$SERVICE_NAME" | run_root tee -a "$KLIPPERAI_MOONRAKER_ALLOWED_SERVICES_PATH" >/dev/null
    return
  fi

  local temp_file
  temp_file="$(mktemp)"
  printf '%s\n' "$SERVICE_NAME" >"$temp_file"
  run_root install -o "$INSTALL_USER" -g "$INSTALL_GROUP" -m 664 "$temp_file" "$KLIPPERAI_MOONRAKER_ALLOWED_SERVICES_PATH"
  rm -f "$temp_file"
}
