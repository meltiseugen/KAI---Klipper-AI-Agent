#!/usr/bin/env bash
# Sourced by install.sh; no work is performed on import.

install_mainsail_custom_nav() {
  [[ -n "${KAI_MAINSAIL_CONFIG_DIR:-}" ]] || die "Mainsail config directory is not set."
  [[ -d "$KAI_MAINSAIL_CONFIG_DIR" ]] || die "Mainsail config directory does not exist: $KAI_MAINSAIL_CONFIG_DIR"

  local href="${KAI_ROOT_PATH%/}/"
  run_as_user bash "$INSTALL_DIR/integrations/mainsail/install-custom-nav.sh" \
    --config-dir "$KAI_MAINSAIL_CONFIG_DIR" \
    --href "$href" \
    --title "KAI" \
    --target "_blank" \
    --position 85
}

install_mainsail_auto_reapply() {
  bash "$INSTALL_DIR/integrations/mainsail/install-auto-reapply.sh" \
    --config-dir "$KAI_MAINSAIL_CONFIG_DIR" \
    --href "${KAI_ROOT_PATH%/}/" --title "KAI" \
    --target "_blank" --position 85 --user "$INSTALL_USER"
}

install_octoeverywhere_integration() {
  [[ -n "${KAI_OE_ROOT:-}" ]] || die "OctoEverywhere checkout path is not set."
  local script_path="$INSTALL_DIR/integrations/octoeverywhere/apply-local-kai-route-patch.sh"
  [[ -f "$script_path" ]] || die "OctoEverywhere integration helper not found: $script_path"

  local cmd=(bash "$script_path" --oe-root "$KAI_OE_ROOT" --kai-prefix "$KAI_ROOT_PATH" --kai-port "$KAI_PORT" --nav-target "_blank")
  if [[ -n "${KAI_OE_SERVICE_NAME:-}" ]]; then
    cmd+=(--restart-service --service "$KAI_OE_SERVICE_NAME")
  fi

  "${cmd[@]}"
}

install_octoeverywhere_auto_reapply() {
  [[ -n "${KAI_OE_ROOT:-}" ]] || die "OctoEverywhere checkout path is not set."
  local script_path="$INSTALL_DIR/integrations/octoeverywhere/install-auto-reapply.sh"
  [[ -f "$script_path" ]] || die "OctoEverywhere auto-reapply helper not found: $script_path"

  local cmd=(sh "$script_path" --install-dir "$INSTALL_DIR" --oe-root "$KAI_OE_ROOT" --kai-prefix "$KAI_ROOT_PATH" --kai-port "$KAI_PORT" --nav-target "_blank" --moonraker-url "$KAI_MOONRAKER_URL")
  if [[ -n "${KAI_OE_SERVICE_NAME:-}" ]]; then
    cmd+=(--service "$KAI_OE_SERVICE_NAME")
  fi

  "${cmd[@]}"
}
