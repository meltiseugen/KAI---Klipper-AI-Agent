#!/usr/bin/env bash
# Sourced by install.sh; no work is performed on import.

write_moonraker_extension_cfg() {
  local temp_file
  local managed_service="managed_services: kai-agent"
  [[ "${KAI_SERVICE_MANAGER:-systemd}" != appliance ]] || managed_service="# Native service lifecycle is managed by /etc/init.d/S99kai."
  temp_file="$(mktemp)"

  cat >"$temp_file" <<EOF
# KAI Moonraker integration
#
# This file is included from moonraker.conf so that KAI appears in
# Moonraker's update manager and can be managed from Mainsail.

[update_manager kai-agent]
type: git_repo
channel: dev
path: $INSTALL_DIR
origin: $KAI_GIT_ORIGIN
primary_branch: $KAI_GIT_PRIMARY_BRANCH
$managed_service
info_tags:
    desc=KAI
EOF

  if [[ -f "$KAI_MOONRAKER_EXTENSION_CFG_PATH" ]] && [[ "$(run_root cat "$KAI_MOONRAKER_EXTENSION_CFG_PATH")" == "$(cat "$temp_file")" ]]; then
    rm -f "$temp_file"
    return
  fi
  mark_moonraker_restart_required
  run_root install -d -o "$INSTALL_USER" -g "$INSTALL_GROUP" -m 755 "$KAI_MANAGED_CONFIG_DIR_PATH"
  backup_file "$KAI_MOONRAKER_EXTENSION_CFG_PATH"
  run_root install -o "$INSTALL_USER" -g "$INSTALL_GROUP" -m 664 "$temp_file" "$KAI_MOONRAKER_EXTENSION_CFG_PATH"
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
  include_line="$(build_include_line "$KAI_MOONRAKER_EXTENSION_CFG_PATH" "$KAI_MOONRAKER_CONFIG_PATH")"
  local legacy_include_line="[include $(basename "$KAI_LEGACY_MOONRAKER_EXTENSION_CFG_PATH")]"

  [[ -f "$KAI_MOONRAKER_CONFIG_PATH" ]] || die "Moonraker config file not found: $KAI_MOONRAKER_CONFIG_PATH"
  if [[ "$legacy_include_line" != "$include_line" ]]; then
    if grep -Fqx "$legacy_include_line" "$KAI_MOONRAKER_CONFIG_PATH"; then mark_moonraker_restart_required; fi
    remove_line_from_file_if_present "$KAI_MOONRAKER_CONFIG_PATH" "$legacy_include_line"
  fi
  if grep -Fqx "$include_line" "$KAI_MOONRAKER_CONFIG_PATH"; then
    return
  fi

  mark_moonraker_restart_required
  backup_file "$KAI_MOONRAKER_CONFIG_PATH"
  printf '\n%s\n' "$include_line" | run_root tee -a "$KAI_MOONRAKER_CONFIG_PATH" >/dev/null
}

ensure_moonraker_allowed_service() {
  if [[ -f "$KAI_MOONRAKER_ALLOWED_SERVICES_PATH" ]] && grep -Fqx "$SERVICE_NAME" "$KAI_MOONRAKER_ALLOWED_SERVICES_PATH"; then
    return
  fi

  mark_moonraker_restart_required
  run_root install -d -o "$INSTALL_USER" -g "$INSTALL_GROUP" -m 755 "$KAI_PRINTER_DATA_ROOT"
  if [[ -f "$KAI_MOONRAKER_ALLOWED_SERVICES_PATH" ]]; then
    backup_file "$KAI_MOONRAKER_ALLOWED_SERVICES_PATH"
    printf '%s\n' "$SERVICE_NAME" | run_root tee -a "$KAI_MOONRAKER_ALLOWED_SERVICES_PATH" >/dev/null
    return
  fi

  local temp_file
  temp_file="$(mktemp)"
  printf '%s\n' "$SERVICE_NAME" >"$temp_file"
  run_root install -o "$INSTALL_USER" -g "$INSTALL_GROUP" -m 664 "$temp_file" "$KAI_MOONRAKER_ALLOWED_SERVICES_PATH"
  rm -f "$temp_file"
}
