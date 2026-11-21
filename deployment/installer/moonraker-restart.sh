#!/usr/bin/env bash
# Installer-only lifecycle control. Never exposed by the read-only agent runtime.

moonraker_restart_marker() {
  printf '%s' "${KAI_MOONRAKER_RESTART_MARKER:-/etc/kai/moonraker-restart-required}"
}

mark_moonraker_restart_required() {
  KAI_MOONRAKER_RESTART_REQUIRED=yes
  local marker temp_file
  marker="$(moonraker_restart_marker)"
  run_root test ! -L "$marker" || die "Moonraker restart marker must not be redirected."
  temp_file="$(mktemp)"
  printf '%s\n' 'KAI integration changes await a Moonraker restart.' >"$temp_file"
  run_root install -d -m 755 "${marker%/*}"
  run_root install -m 600 "$temp_file" "$marker"
  rm -f "$temp_file"
}

finish_moonraker_integration() {
  local marker
  marker="$(moonraker_restart_marker)"
  KAI_MOONRAKER_RESTART_STATUS=not-needed
  if [[ "${KAI_MOONRAKER_RESTART_REQUIRED:-no}" != yes ]] && ! run_root test -e "$marker"; then
    log "Moonraker integration is unchanged; no restart needed."
    return
  fi
  KAI_MOONRAKER_RESTART_STATUS=deferred
  if [[ "${KAI_SERVICE_MANAGER:-systemd}" == appliance ]]; then
    warn "Moonraker reload is pending. Use the native host's Moonraker restart command when idle."
    return
  fi
  if ! run_as_user "$INSTALL_DIR/.venv/bin/python" -m deployment.moonraker_restart --check-idle --url "$KAI_MOONRAKER_URL"; then
    warn "Moonraker restart deferred: the printer is busy or its idle state cannot be verified. When idle, run: sudo systemctl restart moonraker"
    return
  fi
  log "Restarting Moonraker to load the changed KAI integration."
  KAI_MOONRAKER_RESTART_STATUS=failed
  if ! run_root systemctl restart moonraker.service; then
    warn "Moonraker restart failed; integration remains pending. Check: systemctl status moonraker --no-pager"
    return 1
  fi
  if ! run_as_user "$INSTALL_DIR/.venv/bin/python" -m deployment.moonraker_restart --wait-ready --url "$KAI_MOONRAKER_URL"; then
    warn "Moonraker did not become ready after restart; integration remains pending. Check: systemctl status moonraker --no-pager"
    return 1
  fi
  run_root rm -f -- "$marker"
  KAI_MOONRAKER_RESTART_REQUIRED=no
  KAI_MOONRAKER_RESTART_STATUS=restarted
  log "Moonraker restarted and its printer connection is ready."
}
