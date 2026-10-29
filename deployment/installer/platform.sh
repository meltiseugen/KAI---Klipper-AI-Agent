#!/usr/bin/env bash
# Distinguish real systemd from Creality's compatibility systemctl command.

select_service_manager() {
  KLIPPERAI_SERVICE_MANAGER="${KLIPPERAI_SERVICE_MANAGER:-auto}"
  if [[ "$KLIPPERAI_SERVICE_MANAGER" == auto ]]; then
    if [[ -d /run/systemd/system && "$(cat /proc/1/comm 2>/dev/null)" == systemd ]]; then
      KLIPPERAI_SERVICE_MANAGER=systemd
    elif [[ -d /etc/init.d && ( -d /usr/data/printer_data || -d /usr/data/printer_1_data || -d /usr/data/printer_2_data || -d /usr/data/printer_3_data ) ]]; then
      KLIPPERAI_SERVICE_MANAGER=appliance
    else
      KLIPPERAI_SERVICE_MANAGER=systemd
    fi
  fi
  case "$KLIPPERAI_SERVICE_MANAGER" in
    systemd) ;;
    appliance)
      [[ "$(id -u)" -eq 0 ]] || die "Run the native Creality/appliance installer as root."
      [[ -d /etc/init.d ]] || die "Native init directory /etc/init.d is missing."
      ;;
    *) die "KLIPPERAI_SERVICE_MANAGER must be auto, systemd or appliance." ;;
  esac
}

install_appliance_credentials() {
  set +x
  local environment_file="${KLIPPERAI_ENV_PATH:-/etc/klipperai/klipperai.env}"
  log "Provisioning host-encrypted credentials for the native appliance service."
  # Host-key encryption preserves ciphertext at rest, but cannot protect a full disk copy.
  printf '%s' "$KLIPPERAI_OPENAI_API_KEY" | run_as_user "$INSTALL_DIR/.venv/bin/python" \
    -m deployment.appliance_install --install-dir "$INSTALL_DIR" \
    --environment-file "$environment_file" \
    --storage-dir "$KLIPPERAI_DATA_DIR/private" \
    --legacy-storage-dir "$INSTALL_HOME/.config/klipperai" \
    --legacy-config-file "$KLIPPERAI_CFG_PATH" \
    --printer-data-root "$KLIPPERAI_PRINTER_DATA_ROOT" \
    --provider "$KLIPPERAI_LLM_PROVIDER" --model "$KLIPPERAI_OPENAI_MODEL"
  unset KLIPPERAI_OPENAI_API_KEY
  sanitize_legacy_environment_files
}

start_appliance_service() {
  run_root /etc/init.d/S99klipperai start
  run_as_user "$INSTALL_DIR/.venv/bin/python" -c \
    'from pathlib import Path; import sys; from deployment.releases import ReleaseUpdater; ReleaseUpdater(Path(sys.argv[1]), sys.argv[2]).wait_ready(None)' \
    "$INSTALL_DIR" "http://127.0.0.1:$KLIPPERAI_PORT/readyz"
}
