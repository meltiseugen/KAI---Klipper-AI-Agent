#!/usr/bin/env bash
# Sourced by install.sh; no work is performed on import.

print_summary() {
  cat <<EOF

Install summary
---------------
User:                 $INSTALL_USER
Project checkout:     $INSTALL_DIR
Moonraker URL:        $KAI_MOONRAKER_URL
Moonraker config:     $KAI_MOONRAKER_CONFIG_PATH
Printer data root:    $KAI_PRINTER_DATA_ROOT
Mainsail config dir:  $KAI_MAINSAIL_CONFIG_DIR
Managed config dir:   $KAI_MANAGED_CONFIG_DIR_PATH
KAI cfg:         $KAI_CFG_PATH
Moonraker ext cfg:    $KAI_MOONRAKER_EXTENSION_CFG_PATH
Provider:             $KAI_LLM_PROVIDER
Model:                $KAI_OPENAI_MODEL
Root path:            $KAI_ROOT_PATH
nginx server block:   $KAI_NGINX_SERVER_BLOCK_PATH
Patch nginx include:  $PATCH_NGINX_INCLUDE
Local bind port:      $KAI_PORT
Data dir:             $KAI_DATA_DIR
Runtime mode:         read-only
Credential backend:   ${KAI_CREDENTIAL_BACKEND:-native-host}
KAI log file:        $KAI_DATA_DIR/logs/$KAI_AGENT_LOG_FILE_NAME
Mainsail nav link:        $INSTALL_MAINSAIL_NAV
Mainsail auto-reapply:    $INSTALL_MAINSAIL_AUTO_REAPPLY
OctoEverywhere patch:     $INSTALL_OCTOEVERYWHERE_PATCH
OE patch auto-reapply:    $INSTALL_OCTOEVERYWHERE_AUTO_REAPPLY

EOF
}
