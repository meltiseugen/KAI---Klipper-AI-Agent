#!/usr/bin/env bash
# Sourced by install.sh; no work is performed on import.

print_next_steps() {
  if [[ "${KLIPPERAI_SERVICE_MANAGER:-systemd}" == appliance ]]; then
    cat <<EOF

Native KlipperAI installation complete
- Service: /etc/init.d/S99klipperai {start|stop|restart|status}
- Config: $KLIPPERAI_CFG_PATH
- Runtime log: $KLIPPERAI_DATA_DIR/logs/$KLIPPERAI_AGENT_LOG_FILE_NAME
- UI: http://<printer-host>${KLIPPERAI_ROOT_PATH}/
- Deploy fixes from your development machine with: python -m tools.deploy <printer-profile>
- Restart Moonraker manually using the host's own service command to load its new include.
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
  /etc/klipperai/klipperai.env

Editable config file:
  $KLIPPERAI_CFG_PATH

Generated nginx snippet:
  /etc/klipperai/nginx-location.conf

KlipperAI runtime log:
  $KLIPPERAI_DATA_DIR/logs/$KLIPPERAI_AGENT_LOG_FILE_NAME

Next steps:
1. Restart Moonraker so it reloads the KlipperAI include and allowed-services file:
   sudo systemctl restart moonraker
2. Check the services:
   systemctl status $SERVICE_NAME --no-pager
   systemctl status moonraker --no-pager
   tail -n 100 $KLIPPERAI_DATA_DIR/logs/$KLIPPERAI_AGENT_LOG_FILE_NAME
3. Open KlipperAI:
   http://<printer-host>${KLIPPERAI_ROOT_PATH}/
4. After editing ${KLIPPERAI_CFG_PATH}, restart the service:
   sudo systemctl restart $SERVICE_NAME

EOF

  if [[ "${INSTALL_MAINSAIL_AUTO_REAPPLY:-no}" == "yes" ]]; then
    cat <<EOF
Mainsail navigation auto-reapply:
- Checks at startup (after about 30 seconds), on file changes and every 5 minutes.
- Status: systemctl status klipperai-mainsail-reapply.timer klipperai-mainsail-reapply.path
- Logs: journalctl -u klipperai-mainsail-reapply.service -n 50 --no-pager

EOF
  fi

  if [[ "$INSTALL_OCTOEVERYWHERE_PATCH" == "yes" ]]; then
    cat <<EOF

OctoEverywhere integration:
- Checkout: $KLIPPERAI_OE_ROOT
- Service: ${KLIPPERAI_OE_SERVICE_NAME:-<restart manually>}
- Navigation target: new tab
- Route: ${KLIPPERAI_ROOT_PATH%/}/
- Auto-reapply timer: $INSTALL_OCTOEVERYWHERE_AUTO_REAPPLY
- When enabled, checks at startup (after about 30 seconds), on file changes and every 5 minutes.

EOF
  fi

  if [[ "$PATCH_NGINX_INCLUDE" == "yes" ]]; then
    cat <<EOF

nginx:
- Patched: $KLIPPERAI_NGINX_SERVER_BLOCK_PATH
- Included snippet: /etc/klipperai/nginx-location.conf
- Reloaded: yes

If you enabled the Mainsail custom navigation entry:
- reload the Mainsail page after nginx reload
- the nav link is stored in ${KLIPPERAI_MAINSAIL_CONFIG_DIR}/.theme/navi.json
- the agent config is stored in ${KLIPPERAI_CFG_PATH}
- the Moonraker integration include is stored in ${KLIPPERAI_MOONRAKER_EXTENSION_CFG_PATH}
- you can rerun the helper manually with:
  bash $INSTALL_DIR/integrations/mainsail/install-custom-nav.sh --config-dir $KLIPPERAI_MAINSAIL_CONFIG_DIR --href ${KLIPPERAI_ROOT_PATH%/}/

Current limitations:
- the optional native Mainsail drawer patch is not installed by this script
- the KlipperAI runtime is intentionally read-only and will not write printer/config files
- Moonraker update-manager controls work best after the repo has semantic-version tags like v0.1.0

EOF
  else
    cat <<EOF

Manual nginx follow-up:
- Add this line inside the Mainsail nginx server block:
  include /etc/klipperai/nginx-location.conf;
- Common file locations are often:
  - /etc/nginx/conf.d/mainsail.conf
  - /etc/nginx/sites-enabled/mainsail
  - /etc/nginx/sites-available/mainsail
- Test and reload nginx:
  sudo nginx -t && sudo systemctl reload nginx

If you enabled the Mainsail custom navigation entry:
- reload the Mainsail page after nginx reload
- the nav link is stored in ${KLIPPERAI_MAINSAIL_CONFIG_DIR}/.theme/navi.json
- the agent config is stored in ${KLIPPERAI_CFG_PATH}
- the Moonraker integration include is stored in ${KLIPPERAI_MOONRAKER_EXTENSION_CFG_PATH}
- you can rerun the helper manually with:
  bash $INSTALL_DIR/integrations/mainsail/install-custom-nav.sh --config-dir $KLIPPERAI_MAINSAIL_CONFIG_DIR --href ${KLIPPERAI_ROOT_PATH%/}/

Current limitations:
- the optional native Mainsail drawer patch is not installed by this script
- the KlipperAI runtime is intentionally read-only and will not write printer/config files
- Moonraker update-manager controls work best after the repo has semantic-version tags like v0.1.0

EOF
  fi
}
