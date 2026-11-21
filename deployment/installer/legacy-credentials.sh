#!/usr/bin/env bash
# systemd 247 supports LoadCredential from a root-only local stream socket.

install_legacy_systemd_credentials() {
  local legacy_directory="$INSTALL_HOME/.config/kai"
  local configured_directory=""
  if [[ -f /etc/kai/kai.env ]]; then
    configured_directory="$(run_root awk -F= '/^KAI_PROVIDER_STORAGE_DIR=/ { value=substr($0,index($0,"=")+1); gsub(/^"|"$/, "", value); print value; exit }' /etc/kai/kai.env)"
    [[ -z "$configured_directory" ]] || legacy_directory="$configured_directory"
  fi
  warn "Using systemd 247 host-key encryption; a complete disk image can still permit decryption."
  run_root "$INSTALL_DIR/.venv/bin/python" -m deployment.systemd_legacy_install
  run_root systemctl daemon-reload
  run_root systemctl start kai-credentials.socket
  if systemctl is-active --quiet "$SERVICE_NAME"; then
    run_root systemctl stop "$SERVICE_NAME"
  fi
  printf '%s' "$KAI_OPENAI_API_KEY" | run_root systemd-run --quiet --wait --pipe --collect \
    --unit=kai-credential-setup \
    --property="User=$INSTALL_USER" --property=UMask=0077 --property=LimitCORE=0 \
    --property=NoNewPrivileges=yes --property="WorkingDirectory=$INSTALL_DIR" \
    --property="LoadCredential=kai-provider-master:/run/kai-credentials.sock" \
    "$INSTALL_DIR/.venv/bin/python" -m kai_agent.cli.credentials \
    --storage-dir "$KAI_DATA_DIR/private" \
    --legacy-storage-dir "$legacy_directory" --legacy-config-file "$KAI_CFG_PATH" \
    --checkout-dir "$INSTALL_DIR" --printer-data-root "$KAI_PRINTER_DATA_ROOT" \
    --provider "$KAI_LLM_PROVIDER" --model "$KAI_OPENAI_MODEL"
  unset KAI_OPENAI_API_KEY
  sanitize_legacy_environment_files
}
