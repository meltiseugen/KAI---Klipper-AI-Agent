#!/usr/bin/env bash
# Sourced by install.sh; no work is performed on import.

install_mainsail_custom_nav() {
  [[ -n "${KLIPPERAI_MAINSAIL_CONFIG_DIR:-}" ]] || die "Mainsail config directory is not set."
  [[ -d "$KLIPPERAI_MAINSAIL_CONFIG_DIR" ]] || die "Mainsail config directory does not exist: $KLIPPERAI_MAINSAIL_CONFIG_DIR"

  local href="${KLIPPERAI_ROOT_PATH%/}/"
  run_as_user bash "$INSTALL_DIR/integrations/mainsail/install-custom-nav.sh" \
    --config-dir "$KLIPPERAI_MAINSAIL_CONFIG_DIR" \
    --href "$href" \
    --title "KlipperAI" \
    --target "_blank" \
    --position 85
}

install_octoeverywhere_integration() {
  [[ -n "${KLIPPERAI_OE_ROOT:-}" ]] || die "OctoEverywhere checkout path is not set."
  local script_path="$INSTALL_DIR/integrations/octoeverywhere/apply-local-klipperai-route-patch.sh"
  [[ -f "$script_path" ]] || die "OctoEverywhere integration helper not found: $script_path"

  local cmd=(bash "$script_path" --oe-root "$KLIPPERAI_OE_ROOT" --klipperai-prefix "$KLIPPERAI_ROOT_PATH" --klipperai-port "$KLIPPERAI_PORT" --nav-target "_blank")
  if [[ -n "${KLIPPERAI_OE_SERVICE_NAME:-}" ]]; then
    cmd+=(--restart-service --service "$KLIPPERAI_OE_SERVICE_NAME")
  fi

  "${cmd[@]}"
}

install_octoeverywhere_auto_reapply() {
  [[ -n "${KLIPPERAI_OE_ROOT:-}" ]] || die "OctoEverywhere checkout path is not set."
  local script_path="$INSTALL_DIR/integrations/octoeverywhere/install-auto-reapply.sh"
  [[ -f "$script_path" ]] || die "OctoEverywhere auto-reapply helper not found: $script_path"

  local cmd=(sh "$script_path" --install-dir "$INSTALL_DIR" --oe-root "$KLIPPERAI_OE_ROOT" --klipperai-prefix "$KLIPPERAI_ROOT_PATH" --klipperai-port "$KLIPPERAI_PORT" --nav-target "_blank" --moonraker-url "$KLIPPERAI_MOONRAKER_URL")
  if [[ -n "${KLIPPERAI_OE_SERVICE_NAME:-}" ]]; then
    cmd+=(--service "$KLIPPERAI_OE_SERVICE_NAME")
  fi

  "${cmd[@]}"
}
