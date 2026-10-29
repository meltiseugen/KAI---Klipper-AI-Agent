#!/usr/bin/env bash
# Sourced by install.sh; no work is performed on import.

install_service_configuration() {
  log "Provisioning encrypted provider credentials."
  install_encrypted_credentials

  log "Writing /etc/klipperai/klipperai.env"
  write_env_file

  log "Writing ${KLIPPERAI_CFG_PATH}"
  write_cfg_file
  if [[ "$KLIPPERAI_LEGACY_CFG_PATH" != "$KLIPPERAI_CFG_PATH" ]]; then
    retire_legacy_file_if_present "$KLIPPERAI_LEGACY_CFG_PATH"
  fi

  log "Detecting printer profile into ${KLIPPERAI_CFG_PATH}"
  if ! run_as_user "$INSTALL_DIR/.venv/bin/klipperai-detect-profile" \
    --config-file "$KLIPPERAI_CFG_PATH" \
    --moonraker-url "$KLIPPERAI_MOONRAKER_URL" \
    --printer-data-root "$KLIPPERAI_PRINTER_DATA_ROOT" \
    --overwrite
  then
    warn "Automatic printer profile detection failed. You can edit the printer profile sections in ${KLIPPERAI_CFG_PATH} later."
  fi

  log "Writing ${KLIPPERAI_MOONRAKER_EXTENSION_CFG_PATH}"
  write_moonraker_extension_cfg
  if [[ "$KLIPPERAI_LEGACY_MOONRAKER_EXTENSION_CFG_PATH" != "$KLIPPERAI_MOONRAKER_EXTENSION_CFG_PATH" ]]; then
    retire_legacy_file_if_present "$KLIPPERAI_LEGACY_MOONRAKER_EXTENSION_CFG_PATH"
  fi

  log "Adding KlipperAI include to ${KLIPPERAI_MOONRAKER_CONFIG_PATH}"
  ensure_moonraker_include

  if [[ "${KLIPPERAI_SERVICE_MANAGER:-systemd}" == systemd ]]; then
    log "Allowing Moonraker to manage ${SERVICE_NAME}"
    ensure_moonraker_allowed_service
    log "Writing systemd service."
    write_systemd_service
  fi

  configure_nginx
}
