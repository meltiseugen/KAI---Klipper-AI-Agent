#!/usr/bin/env bash
# Sourced by install.sh; no work is performed on import.

configure_options() {
  set +x
  export -n KLIPPERAI_OPENAI_API_KEY
  KLIPPERAI_LLM_PROVIDER="$(prompt_default "LLM provider (currently: openai)" "openai")"
  KLIPPERAI_LLM_PROVIDER="${KLIPPERAI_LLM_PROVIDER,,}"
  KLIPPERAI_OPENAI_MODEL="$(prompt_default "Model name" "gpt-5.4-mini")"
  KLIPPERAI_OPENAI_API_KEY=""

  case "$KLIPPERAI_LLM_PROVIDER" in
    openai)
      KLIPPERAI_OPENAI_API_KEY="$(prompt_secret "OpenAI API key (leave empty to configure in the web page)")"
      if [[ -z "$KLIPPERAI_OPENAI_API_KEY" ]]; then
        warn "The agent requires an API key. Configure it in the web page before using Chat or Debug."
      fi
      ;;
    *)
      die "Unsupported provider '$KLIPPERAI_LLM_PROVIDER'. Current installer support is: openai."
      ;;
  esac

  KLIPPERAI_ENABLE_WRITE_ACTIONS="false"

  INSTALL_MAINSAIL_AUTO_REAPPLY="no"
  if confirm "Install a Mainsail custom-navigation link to KlipperAI?" "Y"; then
    INSTALL_MAINSAIL_NAV="yes"
    if [[ "${KLIPPERAI_SERVICE_MANAGER:-systemd}" == systemd ]] && confirm "Keep the Mainsail link restored at startup and after navigation changes?" "Y"; then
      INSTALL_MAINSAIL_AUTO_REAPPLY="yes"
    fi
  else
    INSTALL_MAINSAIL_NAV="no"
  fi

  if confirm "Patch the Mainsail nginx server block automatically?" "Y"; then
    PATCH_NGINX_INCLUDE="yes"
    KLIPPERAI_NGINX_SERVER_BLOCK_PATH="$(prompt_default "nginx server block path" "$(detect_nginx_server_block_path)")"
    ensure_no_spaces "$KLIPPERAI_NGINX_SERVER_BLOCK_PATH" "nginx server block path"
    [[ -f "$KLIPPERAI_NGINX_SERVER_BLOCK_PATH" ]] || die "nginx server block file not found: $KLIPPERAI_NGINX_SERVER_BLOCK_PATH"
  else
    PATCH_NGINX_INCLUDE="no"
    KLIPPERAI_NGINX_SERVER_BLOCK_PATH="$(detect_nginx_server_block_path)"
  fi

  if [[ "$INSTALL_MAINSAIL_NAV" == "yes" ]] && [[ ! -d "$KLIPPERAI_MAINSAIL_CONFIG_DIR" ]]; then
    die "Mainsail config directory does not exist: $KLIPPERAI_MAINSAIL_CONFIG_DIR"
  fi

  if [[ -n "$KLIPPERAI_OE_ROOT" ]]; then
    log "Detected OctoEverywhere checkout at $KLIPPERAI_OE_ROOT."
    if confirm "Apply the optional OctoEverywhere /klipperai integration now?" "N"; then
      INSTALL_OCTOEVERYWHERE_PATCH="yes"
      if [[ "${KLIPPERAI_SERVICE_MANAGER:-systemd}" == systemd ]] && confirm "Install an auto-reapply timer for the OctoEverywhere patch after future OE updates?" "Y"; then
        INSTALL_OCTOEVERYWHERE_AUTO_REAPPLY="yes"
      fi
    fi
  else
    INSTALL_OCTOEVERYWHERE_PATCH="unavailable"
    INSTALL_OCTOEVERYWHERE_AUTO_REAPPLY="unavailable"
  fi

  print_summary
  confirm "Proceed with installation?" "Y" || die "Installation cancelled."
}
