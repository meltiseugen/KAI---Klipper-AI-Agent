#!/usr/bin/env bash
# Sourced by install.sh; no work is performed on import.

print_summary() {
  cat <<EOF

Install summary
---------------
User:                 $INSTALL_USER
Project checkout:     $INSTALL_DIR
Moonraker URL:        $KLIPPERAI_MOONRAKER_URL
Moonraker config:     $KLIPPERAI_MOONRAKER_CONFIG_PATH
Printer data root:    $KLIPPERAI_PRINTER_DATA_ROOT
Mainsail config dir:  $KLIPPERAI_MAINSAIL_CONFIG_DIR
Managed config dir:   $KLIPPERAI_MANAGED_CONFIG_DIR_PATH
KlipperAI cfg:         $KLIPPERAI_CFG_PATH
Moonraker ext cfg:    $KLIPPERAI_MOONRAKER_EXTENSION_CFG_PATH
Provider:             $KLIPPERAI_LLM_PROVIDER
Model:                $KLIPPERAI_OPENAI_MODEL
Root path:            $KLIPPERAI_ROOT_PATH
nginx server block:   $KLIPPERAI_NGINX_SERVER_BLOCK_PATH
Patch nginx include:  $PATCH_NGINX_INCLUDE
Local bind port:      $KLIPPERAI_PORT
Data dir:             $KLIPPERAI_DATA_DIR
Runtime mode:         read-only
KlipperAI log file:        $KLIPPERAI_LOGS_DIR_PATH/$KLIPPERAI_AGENT_LOG_FILE_NAME
Mainsail nav link:        $INSTALL_MAINSAIL_NAV
OctoEverywhere patch:     $INSTALL_OCTOEVERYWHERE_PATCH
OE patch auto-reapply:    $INSTALL_OCTOEVERYWHERE_AUTO_REAPPLY

EOF
}
