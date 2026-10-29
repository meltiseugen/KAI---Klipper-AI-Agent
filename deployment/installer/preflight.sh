#!/usr/bin/env bash
# Sourced by install.sh; no work is performed on import.

preflight() {
  require_linux
  select_service_manager
  [[ -f "$SCRIPT_DIR/pyproject.toml" ]] || die "Run this installer from a KlipperAI checkout."
  ensure_prerequisites
  require_cmd awk
  require_cmd find
  require_cmd git
  require_cmd grep
  require_cmd install
  require_cmd python3
  require_cmd stat
  if [[ "$KLIPPERAI_SERVICE_MANAGER" == systemd ]]; then
    require_cmd systemctl
    require_cmd systemd-creds
    require_cmd systemd-run
    local systemd_version
    systemd_version="$(systemd-creds --version | awk 'NR == 1 {print $2}')"
    [[ "$systemd_version" =~ ^[0-9]+$ && "$systemd_version" -ge 250 ]] || die "Secure credential storage requires systemd 250 or newer."
  fi

  log "Preparing interactive installation."
}
