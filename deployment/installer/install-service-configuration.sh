#!/usr/bin/env bash
# Sourced by install.sh; no work is performed on import.

install_service_configuration() {
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

  log "Allowing Moonraker to manage ${SERVICE_NAME}"
  ensure_moonraker_allowed_service

  log "Writing systemd service."
  write_systemd_service

  log "Generating nginx location snippet."
  write_nginx_snippet

  if [[ "$PATCH_NGINX_INCLUDE" == "yes" ]]; then
    log "Patching nginx server block."
    ensure_nginx_include
    log "Testing and reloading nginx."
    if ! reload_nginx; then
      if [[ -f "${KLIPPERAI_NGINX_SERVER_BLOCK_PATH}.bak.${TIMESTAMP}" ]]; then
        warn "nginx validation failed after patching $KLIPPERAI_NGINX_SERVER_BLOCK_PATH. Restoring the previous file."
        run_root cp "${KLIPPERAI_NGINX_SERVER_BLOCK_PATH}.bak.${TIMESTAMP}" "$KLIPPERAI_NGINX_SERVER_BLOCK_PATH"
      fi
      die "nginx validation failed after patching $KLIPPERAI_NGINX_SERVER_BLOCK_PATH."
    fi
  fi
}
