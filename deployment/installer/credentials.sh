#!/usr/bin/env bash
# Sourced by install.sh; secret input is never an external command argument.

sanitize_legacy_environment_files() {
  local path temp_file
  for path in /etc/klipperai/klipperai.env /etc/klipperai/klipperai.env.bak.*; do
    [[ -e "$path" || -L "$path" ]] || continue
    [[ -f "$path" && ! -L "$path" && "$(stat -c '%h' "$path")" == 1 ]] || die "Unsafe environment file: $path"
    temp_file="$(mktemp)"
    if ! run_root awk '!/^[[:space:]]*(export[[:space:]]+)?(KLIPPERAI_OPENAI_API_KEY|KLIPPYAI_OPENAI_API_KEY|OPENAI_API_KEY)[[:space:]]*=/' "$path" >"$temp_file"; then
      rm -f "$temp_file"
      die "Could not sanitize legacy environment metadata."
    fi
    run_root install -m 600 "$temp_file" "$path"
    rm -f "$temp_file"
  done
}

install_encrypted_credentials() {
  set +x
  if [[ "${KLIPPERAI_SERVICE_MANAGER:-systemd}" == appliance ]]; then
    install_appliance_credentials
    return
  fi
  local credential_dir="/etc/klipperai/credentials"
  local credential_file="$credential_dir/provider-master.cred"
  local protection="host"
  local legacy_directory="$INSTALL_HOME/.config/klipperai"
  local configured_directory
  if [[ -f /etc/klipperai/klipperai.env ]]; then
    configured_directory="$(run_root awk -F= '/^KLIPPERAI_PROVIDER_STORAGE_DIR=/ { value=substr($0,index($0,"=")+1); gsub(/^"|"$/, "", value); print value; exit }' /etc/klipperai/klipperai.env)"
    [[ -z "$configured_directory" ]] || legacy_directory="$configured_directory"
  fi
  if run_root test -L /etc/klipperai || run_root test -L "$credential_dir" || run_root test -L "$credential_file"; then
    die "Credential paths must not be symlinks."
  fi
  run_root install -d -o root -g root -m 755 /etc/klipperai
  run_root install -d -o root -g root -m 700 "$credential_dir"
  if run_root test -e "$credential_file"; then
    run_root test -f "$credential_file" && [[ "$(run_root stat -c '%h' "$credential_file")" == 1 ]] || die "Unsafe master credential file."
    log "Keeping the existing encrypted master credential."
  else
    if run_root systemd-creds has-tpm2 --quiet; then
      protection="host+tpm2"
      log "Protecting credentials with the host key and TPM2."
    else
      warn "TPM2 is unavailable. Credentials will use host-key encryption; a complete disk image can still permit decryption."
    fi
    # Only ciphertext touches disk. Never replace an existing master key.
    run_root bash -c '
      set -euo pipefail
      umask 077
      temporary=$(mktemp "$1/.master.XXXXXX")
      trap '\''rm -f -- "$temporary"'\'' EXIT
      head -c 32 /dev/urandom | systemd-creds encrypt --name=klipperai-provider-master --with-key="$2" - - >"$temporary"
      [[ ! -e "$3" && ! -L "$3" ]]
      ln "$temporary" "$3"
    ' credentials "$credential_dir" "$protection" "$credential_file"
  fi
  run_root chmod 600 "$credential_file"
  run_root chown root:root /etc/klipperai "$credential_dir" "$credential_file"
  # Stop the old daemon before migrating its DB. Klipper and Moonraker are untouched.
  if systemctl is-active --quiet "$SERVICE_NAME"; then
    run_root systemctl stop "$SERVICE_NAME"
  fi
  printf '%s' "$KLIPPERAI_OPENAI_API_KEY" | run_root systemd-run --quiet --wait --pipe --collect \
    --property="User=$INSTALL_USER" --property=UMask=0077 --property=LimitCORE=0 \
    --property=NoNewPrivileges=yes --property="WorkingDirectory=$INSTALL_DIR" \
    --property="LoadCredentialEncrypted=klipperai-provider-master:$credential_file" \
    "$INSTALL_DIR/.venv/bin/python" -m klipperai_agent.cli.credentials \
    --storage-dir "$KLIPPERAI_DATA_DIR/private" \
    --legacy-storage-dir "$legacy_directory" --legacy-config-file "$KLIPPERAI_CFG_PATH" \
    --checkout-dir "$INSTALL_DIR" --printer-data-root "$KLIPPERAI_PRINTER_DATA_ROOT" \
    --provider "$KLIPPERAI_LLM_PROVIDER" --model "$KLIPPERAI_OPENAI_MODEL"
  unset KLIPPERAI_OPENAI_API_KEY
  sanitize_legacy_environment_files
}
