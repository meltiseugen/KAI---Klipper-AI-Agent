#!/usr/bin/env bash
# Distinguish real systemd from Creality's compatibility systemctl command.

select_service_manager() {
  KAI_SERVICE_MANAGER="${KAI_SERVICE_MANAGER:-auto}"
  if [[ "$KAI_SERVICE_MANAGER" == auto ]]; then
    if [[ -d /run/systemd/system && "$(cat /proc/1/comm 2>/dev/null)" == systemd ]]; then
      KAI_SERVICE_MANAGER=systemd
    elif [[ -d /etc/init.d && ( -d /usr/data/printer_data || -d /usr/data/printer_1_data || -d /usr/data/printer_2_data || -d /usr/data/printer_3_data ) ]]; then
      KAI_SERVICE_MANAGER=appliance
    else
      KAI_SERVICE_MANAGER=systemd
    fi
  fi
  case "$KAI_SERVICE_MANAGER" in
    systemd) ;;
    appliance)
      [[ "$(id -u)" -eq 0 ]] || die "Run the native Creality/appliance installer as root."
      [[ -d /etc/init.d ]] || die "Native init directory /etc/init.d is missing."
      ;;
    *) die "KAI_SERVICE_MANAGER must be auto, systemd or appliance." ;;
  esac
}

install_appliance_credentials() {
  set +x
  local environment_file="${KAI_ENV_PATH:-/etc/kai/kai.env}"
  log "Provisioning host-encrypted credentials for the native appliance service."
  # Host-key encryption preserves ciphertext at rest, but cannot protect a full disk copy.
  printf '%s' "$KAI_OPENAI_API_KEY" | run_as_user "$INSTALL_DIR/.venv/bin/python" \
    -m deployment.appliance_install --install-dir "$INSTALL_DIR" \
    --environment-file "$environment_file" \
    --storage-dir "$KAI_DATA_DIR/private" \
    --legacy-storage-dir "$INSTALL_HOME/.config/kai" \
    --legacy-config-file "$KAI_CFG_PATH" \
    --printer-data-root "$KAI_PRINTER_DATA_ROOT" \
    --provider "$KAI_LLM_PROVIDER" --model "$KAI_OPENAI_MODEL"
  unset KAI_OPENAI_API_KEY
  sanitize_legacy_environment_files
}

start_appliance_service() {
  run_root /etc/init.d/S99kai start
  run_as_user "$INSTALL_DIR/.venv/bin/python" -c \
    'from pathlib import Path; import sys; from deployment.releases import ReleaseUpdater; ReleaseUpdater(Path(sys.argv[1]), sys.argv[2]).wait_ready(None)' \
    "$INSTALL_DIR" "http://127.0.0.1:$KAI_PORT/readyz"
}
