#!/usr/bin/env bash
# Sourced by install.sh; no work is performed on import.

install_access_integrations() {
  if [[ "$INSTALL_MAINSAIL_NAV" == "yes" ]]; then
    log "Installing Mainsail custom navigation entry."
    install_mainsail_custom_nav
  fi

  log "Reloading systemd and enabling the service."
  run_root systemctl daemon-reload
  run_root systemctl enable --now "$SERVICE_NAME"

  if [[ "$INSTALL_OCTOEVERYWHERE_PATCH" == "yes" ]]; then
    log "Applying OctoEverywhere /klipperai integration patch."
    install_octoeverywhere_integration
  fi

  if [[ "$INSTALL_OCTOEVERYWHERE_AUTO_REAPPLY" == "yes" ]]; then
    log "Installing OctoEverywhere patch auto-reapply timer."
    install_octoeverywhere_auto_reapply
  fi
}
