#!/usr/bin/env bash
# Sourced by install.sh; no work is performed on import.

print_next_steps() {
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
  $KLIPPERAI_LOGS_DIR_PATH/$KLIPPERAI_AGENT_LOG_FILE_NAME

Next steps:
1. Restart Moonraker so it reloads the KlipperAI include and allowed-services file:
   sudo systemctl restart moonraker
2. Check the services:
   systemctl status $SERVICE_NAME --no-pager
   systemctl status moonraker --no-pager
   tail -n 100 $KLIPPERAI_LOGS_DIR_PATH/$KLIPPERAI_AGENT_LOG_FILE_NAME
3. Open KlipperAI:
   http://<printer-host>${KLIPPERAI_ROOT_PATH}/
4. After editing ${KLIPPERAI_CFG_PATH}, restart the service:
   sudo systemctl restart $SERVICE_NAME

EOF

  if [[ "$INSTALL_OCTOEVERYWHERE_PATCH" == "yes" ]]; then
    cat <<EOF

OctoEverywhere integration:
- Checkout: $KLIPPERAI_OE_ROOT
- Service: ${KLIPPERAI_OE_SERVICE_NAME:-<restart manually>}
- Navigation target: new tab
- Route: ${KLIPPERAI_ROOT_PATH%/}/
- Auto-reapply timer: $INSTALL_OCTOEVERYWHERE_AUTO_REAPPLY

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
