#!/usr/bin/env bash
# Sourced by install.sh; no work is performed on import.

preflight() {
  require_linux
  select_service_manager
  [[ -f "$SCRIPT_DIR/pyproject.toml" ]] || die "Run this installer from a KAI checkout."
  ensure_prerequisites
  require_cmd awk
  require_cmd find
  require_cmd git
  require_cmd grep
  require_cmd install
  require_cmd python3
  require_cmd stat
  if [[ "$KAI_SERVICE_MANAGER" == systemd ]]; then
    require_cmd systemctl
    require_cmd systemd-run
    local systemd_version
    systemd_version="$(systemctl --version | awk 'NR == 1 {print $2}')"
    [[ "$systemd_version" =~ ^[0-9]+$ && "$systemd_version" -ge 247 ]] || die "Secure credential storage requires systemd 247 or newer."
    KAI_CREDENTIAL_BACKEND=systemd
    if [[ "$systemd_version" -lt 250 ]] || run_root test -e /etc/kai/credentials/provider-master.enc || run_root test -L /etc/kai/credentials/provider-master.enc || run_root test -e /etc/kai-host-key/host.key || run_root test -L /etc/kai-host-key/host.key; then
      KAI_CREDENTIAL_BACKEND=legacy-systemd
      run_root test ! -e /etc/kai/credentials/provider-master.cred || die "This host has a systemd encrypted master; preserve it and restore the supported systemd backend."
      run_root test ! -L /etc/kai/credentials/provider-master.cred || die "Credential paths must not be redirected."
    else
      require_cmd systemd-creds
    fi
  fi

  log "Preparing interactive installation."
}
