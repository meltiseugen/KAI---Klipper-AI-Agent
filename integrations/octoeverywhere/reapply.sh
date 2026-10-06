#!/bin/sh
# Sourced by the generated runner after its installation settings.

ROUTER_FILE="$OE_ROOT/moonraker_octoeverywhere/moonrakerapirouter.py"
UI_FILE="$OE_ROOT/moonraker_octoeverywhere/static/oe-ui.js"
PATCH_SCRIPT="$INSTALL_DIR/integrations/octoeverywhere/apply-local-klipperai-route-patch.sh"

log() {
  printf '[KlipperAI OE auto-reapply] %s\n' "$*"
}

patch_is_present() {
  [ -f "$ROUTER_FILE" ] || return 1
  [ -f "$UI_FILE" ] || return 1
  grep -Eq "(KlipperAI|KlippyAI) local route patch init start" "$ROUTER_FILE" || return 1
  grep -Eq "(KlipperAI|KlippyAI) local route patch helper start" "$ROUTER_FILE" || return 1
  grep -Eq "(KlipperAI|KlippyAI) local route patch map start" "$ROUTER_FILE" || return 1
  grep -Eq "(KlipperAI|KlippyAI) local route patch start" "$UI_FILE" || return 1
  return 0
}

[ -f "$PATCH_SCRIPT" ] || {
  log "Patch helper is missing: $PATCH_SCRIPT"
  exit 1
}

commits_behind() {
  python3 - "$MOONRAKER_URL" "$OE_UPDATE_MANAGER" <<'PY'
import json
import sys
import urllib.parse
import urllib.request

base_url = sys.argv[1].rstrip("/")
target = sys.argv[2].lower()
query = urllib.parse.urlencode({"refresh": "false"})
with urllib.request.urlopen(f"{base_url}/machine/update/status?{query}", timeout=15) as response:
    payload = json.load(response)
result = payload["result"]
if result.get("busy", False):
    print("busy")
    raise SystemExit(0)
version_info = result["version_info"]
for name, details in version_info.items():
    if name.lower() == target:
        count = details.get("commits_behind_count")
        if count is None:
            raise SystemExit("Moonraker did not provide commits_behind_count")
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            raise SystemExit("Invalid commits_behind_count")
        print(count)
        break
else:
    raise SystemExit(f"Moonraker updater not found: {sys.argv[2]}")
PY
}

refresh_moonraker_updates() {
  python3 - "$MOONRAKER_URL" "$OE_UPDATE_MANAGER" <<'PY' || true
import sys
import urllib.parse
import urllib.request

base_url = sys.argv[1].rstrip("/")
query = urllib.parse.urlencode({"name": sys.argv[2]})
request = urllib.request.Request(
    f"{base_url}/machine/update/refresh?{query}",
    method="POST",
)
with urllib.request.urlopen(request, timeout=120) as response:
    response.read()
PY
}

apply_patch() {
  sh "$PATCH_SCRIPT" \
    --oe-root "$OE_ROOT" \
    --klipperai-prefix "$KLIPPERAI_PREFIX" \
    --klipperai-port "$KLIPPERAI_PORT" \
    --nav-target "$NAV_TARGET" \
    --restart-service \
    --service "$OE_SERVICE"
}

remove_patch_for_update() {
  sh "$PATCH_SCRIPT" \
    --oe-root "$OE_ROOT" \
    --restore-original \
    --restart-service \
    --service "$OE_SERVICE"
}

BEHIND=""
if ! BEHIND="$(commits_behind)"; then
  log "Could not query Moonraker update state; leaving the current patch state unchanged."
  exit 1
fi

case "$BEHIND" in
  busy)
    log "Moonraker is updating; leaving the checkout unchanged."
    exit 0
    ;;
  ''|*[!0-9]*)
    log "Moonraker returned an invalid commits-behind count: $BEHIND"
    exit 1
    ;;
esac

if [ "$BEHIND" -gt 0 ]; then
  if patch_is_present; then
    log "OctoEverywhere has $BEHIND pending commit(s); removing KlipperAI patch blocks before update."
    remove_patch_for_update
    refresh_moonraker_updates
  else
    log "OctoEverywhere has $BEHIND pending commit(s); checkout is already unpatched and ready to update."
  fi
  exit 0
fi

if [ -f "$SUSPEND_FILE" ]; then
  rm -f "$SUSPEND_FILE"
  log "OctoEverywhere is current; cleared the update suspension marker."
fi

if patch_is_present; then
  log "OctoEverywhere is current and the KlipperAI patch is present."
  exit 0
fi

log "OctoEverywhere is current but the KlipperAI patch is missing; reapplying now."
apply_patch
