#!/bin/sh
# Compatibility adapter for existing generated systemd runners.
# Their saved settings are kept; reinstall the hook to refresh unit definitions.
STATE_DIR="${KAI_STATE_DIR:-$(dirname "${SUSPEND_FILE:-/etc/kai/octoeverywhere-reapply.suspended}")}"
exec sh "$INSTALL_DIR/integrations/octoeverywhere/run-maintenance.sh" \
  --reconcile --state-dir "$STATE_DIR" --oe-root "$OE_ROOT" \
  --kai-prefix "$KAI_PREFIX" --kai-port "$KAI_PORT" \
  --nav-target "$NAV_TARGET" --service "$OE_SERVICE" \
  --moonraker-url "$MOONRAKER_URL" --update-manager "$OE_UPDATE_MANAGER"
