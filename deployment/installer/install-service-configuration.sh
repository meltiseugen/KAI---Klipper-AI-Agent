#!/usr/bin/env bash
# Sourced by install.sh; no work is performed on import.

install_service_configuration() {
  log "Provisioning encrypted provider credentials."
  install_encrypted_credentials

  log "Writing /etc/kai/kai.env"
  write_env_file

  log "Writing ${KAI_CFG_PATH}"
  write_cfg_file
  if [[ "$KAI_LEGACY_CFG_PATH" != "$KAI_CFG_PATH" ]]; then
    retire_legacy_file_if_present "$KAI_LEGACY_CFG_PATH"
  fi

  log "Detecting printer profile into ${KAI_CFG_PATH}"
  if ! run_as_user "$INSTALL_DIR/.venv/bin/kai-detect-profile" \
    --config-file "$KAI_CFG_PATH" \
    --moonraker-url "$KAI_MOONRAKER_URL" \
    --printer-data-root "$KAI_PRINTER_DATA_ROOT" \
    --overwrite
  then
    warn "Automatic printer profile detection failed. You can edit the printer profile sections in ${KAI_CFG_PATH} later."
  fi

  log "Writing ${KAI_MOONRAKER_EXTENSION_CFG_PATH}"
  write_moonraker_extension_cfg
  if [[ "$KAI_LEGACY_MOONRAKER_EXTENSION_CFG_PATH" != "$KAI_MOONRAKER_EXTENSION_CFG_PATH" ]]; then
    retire_legacy_file_if_present "$KAI_LEGACY_MOONRAKER_EXTENSION_CFG_PATH"
  fi

  log "Adding KAI include to ${KAI_MOONRAKER_CONFIG_PATH}"
  ensure_moonraker_include

  if [[ "${KAI_SERVICE_MANAGER:-systemd}" == systemd ]]; then
    log "Allowing Moonraker to manage ${SERVICE_NAME}"
    ensure_moonraker_allowed_service
    log "Writing systemd service."
    write_systemd_service
  fi

  configure_nginx
}
