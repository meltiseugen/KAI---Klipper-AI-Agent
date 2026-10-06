#!/usr/bin/env bash
# Sourced by install.sh; no work is performed on import.

preflight() {
  require_linux
  require_cmd awk
  require_cmd find
  require_cmd git
  require_cmd grep
  require_cmd install
  require_cmd python3
  require_cmd stat
  require_cmd systemctl

  [[ -f "$SCRIPT_DIR/pyproject.toml" ]] || die "Run this installer from a KlipperAI checkout."

  log "Preparing interactive installation."
}
