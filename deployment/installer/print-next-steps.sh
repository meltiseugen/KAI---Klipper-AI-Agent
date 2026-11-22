#!/usr/bin/env bash
# Sourced by install.sh; no work is performed on import.

print_next_steps() {
  if [[ "${KAI_SERVICE_MANAGER:-systemd}" == appliance ]]; then
    cat <<EOF

Native KAI installation complete
- Service: /etc/init.d/S99kai {start|stop|restart|status}
- Config: $KAI_CFG_PATH
- Runtime log: $KAI_DATA_DIR/logs/$KAI_AGENT_LOG_FILE_NAME
- UI: http://<printer-host>${KAI_ROOT_PATH}/
- Deploy fixes from your development machine with: python -m tools.deploy <printer-profile>
- Moonraker reload: ${KAI_MOONRAKER_RESTART_STATUS:-not-needed}. If deferred, use the native host's Moonraker restart command when idle.
- Encrypted credentials use a separate root-only host wrapping key and RAM-only delivery.
- Host-key protection cannot protect a complete disk image or against root access.

EOF
    return
  fi
  cat <<EOF

Installation complete
---------------------
Service name:
  $SERVICE_NAME

Environment file:
  /etc/kai/kai.env

Editable config file:
  $KAI_CFG_PATH

Generated nginx snippet:
  /etc/kai/nginx-location.conf

KAI runtime log:
  $KAI_DATA_DIR/logs/$KAI_AGENT_LOG_FILE_NAME

Next steps:
Moonraker integration: ${KAI_MOONRAKER_RESTART_STATUS:-not-needed}

1. Check the services:
   systemctl status $SERVICE_NAME --no-pager
   systemctl status moonraker --no-pager
   tail -n 100 $KAI_DATA_DIR/logs/$KAI_AGENT_LOG_FILE_NAME
2. Open KAI:
   http://<printer-host>${KAI_ROOT_PATH}/
3. After editing ${KAI_CFG_PATH}, restart the service:
   sudo systemctl restart $SERVICE_NAME

EOF

  if [[ "${KAI_MOONRAKER_RESTART_STATUS:-not-needed}" == deferred ]]; then
    cat <<EOF
Moonraker restart is still pending because idle status could not be verified.
When the printer is idle, run:
  sudo systemctl restart moonraker

EOF
  fi

  if [[ "${INSTALL_MAINSAIL_AUTO_REAPPLY:-no}" == "yes" ]]; then
    cat <<EOF
Mainsail navigation auto-reapply:
- Checks at startup (after about 30 seconds), on file changes and every 5 minutes.
- Status: systemctl status kai-mainsail-reapply.timer kai-mainsail-reapply.path
- Logs: journalctl -u kai-mainsail-reapply.service -n 50 --no-pager

EOF
  fi

  if [[ "$INSTALL_OCTOEVERYWHERE_PATCH" == "yes" ]]; then
    cat <<EOF

OctoEverywhere integration:
- Checkout: $KAI_OE_ROOT
- Service: ${KAI_OE_SERVICE_NAME:-<restart manually>}
- Navigation target: new tab
- Route: ${KAI_ROOT_PATH%/}/
- Auto-reapply timer: $INSTALL_OCTOEVERYWHERE_AUTO_REAPPLY
- When enabled, checks at startup (after about 30 seconds), on file changes and every 5 minutes.
- Available OE updates leave KAI active. Before updating OE, follow integrations/octoeverywhere/README.md to prepare the checkout.

EOF
  fi

  if [[ "$PATCH_NGINX_INCLUDE" == "yes" ]]; then
    cat <<EOF

nginx:
- Patched: $KAI_NGINX_SERVER_BLOCK_PATH
- Included snippet: /etc/kai/nginx-location.conf
- Reloaded: yes

If you enabled the Mainsail custom navigation entry:
- reload the Mainsail page after nginx reload
- the nav link is stored in ${KAI_MAINSAIL_CONFIG_DIR}/.theme/navi.json
- the agent config is stored in ${KAI_CFG_PATH}
- the Moonraker integration include is stored in ${KAI_MOONRAKER_EXTENSION_CFG_PATH}
- you can rerun the helper manually with:
  bash $INSTALL_DIR/integrations/mainsail/install-custom-nav.sh --config-dir $KAI_MAINSAIL_CONFIG_DIR --href ${KAI_ROOT_PATH%/}/

Current limitations:
- the optional native Mainsail drawer patch is not installed by this script
- the KAI runtime is intentionally read-only and will not write printer/config files
- Moonraker update-manager controls work best after the repo has semantic-version tags like v0.1.0

EOF
  else
    cat <<EOF

Manual nginx follow-up:
- Add this line inside the Mainsail nginx server block:
  include /etc/kai/nginx-location.conf;
- Common file locations are often:
  - /etc/nginx/conf.d/mainsail.conf
  - /etc/nginx/sites-enabled/mainsail
  - /etc/nginx/sites-available/mainsail
- Test and reload nginx:
  sudo nginx -t && sudo systemctl reload nginx

If you enabled the Mainsail custom navigation entry:
- reload the Mainsail page after nginx reload
- the nav link is stored in ${KAI_MAINSAIL_CONFIG_DIR}/.theme/navi.json
- the agent config is stored in ${KAI_CFG_PATH}
- the Moonraker integration include is stored in ${KAI_MOONRAKER_EXTENSION_CFG_PATH}
- you can rerun the helper manually with:
  bash $INSTALL_DIR/integrations/mainsail/install-custom-nav.sh --config-dir $KAI_MAINSAIL_CONFIG_DIR --href ${KAI_ROOT_PATH%/}/

Current limitations:
- the optional native Mainsail drawer patch is not installed by this script
- the KAI runtime is intentionally read-only and will not write printer/config files
- Moonraker update-manager controls work best after the repo has semantic-version tags like v0.1.0

EOF
  fi
}
