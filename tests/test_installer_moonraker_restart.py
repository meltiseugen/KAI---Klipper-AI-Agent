"""Installer reloads changed Moonraker integration only with verified idle state."""

import io
import json
from unittest.mock import Mock

import pytest

from deployment import moonraker_restart as checks
from tests.test_installer import ROOT, bash


def status(job="standby", motion="Idle", firmware="ready"):
    return {
        "result": {
            "status": {
                "print_stats": {"state": job},
                "idle_timeout": {"state": motion},
                "webhooks": {"state": firmware},
            }
        }
    }


@pytest.mark.parametrize(
    "job,motion,firmware,allowed",
    [
        ("standby", "Idle", "ready", True),
        ("complete", "Ready", "ready", True),
        ("cancelled", "Idle", "ready", True),
        ("printing", "Idle", "ready", False),
        ("paused", "Idle", "ready", False),
        ("standby", "Printing", "ready", False),
        ("standby", "Idle", "shutdown", False),
        ("unknown", "Idle", "ready", False),
    ],
)
def test_idle_guard_blocks_jobs_pauses_motion_and_firmware_faults(job, motion, firmware, allowed):
    assert checks.idle_status(status(job, motion, firmware)) is allowed


@pytest.mark.parametrize("payload", [{}, {"result": None}, {"result": {"status": []}}])
def test_incomplete_status_never_allows_restart(payload, monkeypatch):
    monkeypatch.setattr(checks, "read_json", lambda url: payload)
    assert not checks.check_idle("http://127.0.0.1:7125")


def test_network_failures_defer_restart_and_ready_wait_recovers(monkeypatch):
    fetch = Mock(side_effect=OSError("offline"))
    monkeypatch.setattr(checks, "read_json", fetch)
    assert not checks.check_idle("http://printer")
    assert not checks.wait_ready("http://printer", timeout=0)
    fetch.side_effect = [
        ValueError("starting"),
        {"result": {"klippy_connected": True, "klippy_state": "ready"}},
    ]
    monkeypatch.setattr(checks.time, "sleep", lambda seconds: None)
    assert checks.wait_ready("http://printer")


def test_http_status_reads_are_bounded_and_do_not_use_environment_proxies(monkeypatch):
    response = io.BytesIO(json.dumps(status()).encode())
    opener = Mock()
    opener.open.return_value = response
    factory = Mock(return_value=opener)
    monkeypatch.setattr(checks.urllib.request, "build_opener", factory)
    assert checks.read_json("http://printer") == status()
    assert factory.call_args.args[0].proxies == {}
    opener.open.assert_called_once_with("http://printer", timeout=3)
    opener.open.return_value = io.BytesIO(b"x" * 65537)
    with pytest.raises(ValueError, match="too large"):
        checks.read_json("http://printer")
    opener.open.return_value = io.BytesIO(b"[]")
    with pytest.raises(ValueError, match="Invalid"):
        checks.read_json("http://printer")


@pytest.mark.parametrize(
    "idle,restart,ready,backend,pending,expected",
    [
        (True, True, True, "systemd", True, "restarted"),
        (False, True, True, "systemd", True, "deferred"),
        (True, False, True, "systemd", True, "failed"),
        (True, True, False, "systemd", True, "failed"),
        (True, True, True, "appliance", True, "deferred"),
        (True, True, True, "systemd", False, "not-needed"),
    ],
)
def test_restart_lifecycle_retains_pending_marker_until_ready(
    tmp_path, run_shell, idle, restart, ready, backend, pending, expected
):
    marker = tmp_path / "pending"
    calls = tmp_path / "calls"
    calls.touch()
    if pending:
        marker.write_text("pending from an earlier install")
    result = bash(
        run_shell,
        """
set -euo pipefail
source "$1/deployment/installer/moonraker-restart.sh"
KAI_MOONRAKER_RESTART_MARKER="$2"
CALLS="$3"
IDLE="$4"
RESTART="$5"
READY="$6"
KAI_SERVICE_MANAGER="$7"
INSTALL_DIR=/home/biqu/KAI
KAI_MOONRAKER_URL=http://127.0.0.1:7125
log() { :; }
warn() { printf '%s\\n' "$*" >&2; }
run_as_user() {
  printf '%s\\n' "$*" >> "$CALLS"
  if [[ "$*" == *--check-idle* ]]; then [[ "$IDLE" == yes ]]; else [[ "$READY" == yes ]]; fi
}
run_root() {
  if [[ "$1" == systemctl ]]; then
    printf '%s\\n' "$*" >> "$CALLS"
    [[ "$RESTART" == yes ]]
  else "$@"; fi
}
if finish_moonraker_integration; then echo completed; else echo failed; fi
printf '%s\\n' "$KAI_MOONRAKER_RESTART_STATUS"
""",
        ROOT.as_posix(),
        marker.as_posix(),
        calls.as_posix(),
        *["yes" if value else "no" for value in (idle, restart, ready)],
        backend,
    )
    assert result.stdout.splitlines()[-1] == expected
    commands = calls.read_text()
    assert ("systemctl restart moonraker.service" in commands) is (
        pending and idle and backend == "systemd"
    )
    assert "restart klipper" not in commands
    assert marker.exists() is (pending and expected != "restarted")
    if expected == "failed":
        assert "failed" in result.stdout


def test_integration_file_changes_mark_pending_but_identical_reinstall_does_not(
    tmp_path, run_shell
):
    config = tmp_path / "config"
    config.mkdir()
    (config / "moonraker.conf").write_text("[server]\n")
    (config / "printer.cfg").write_text("[printer]\nkinematics: corexy\n")
    bash(
        run_shell,
        """
set -euo pipefail
source "$1/deployment/installer/common.sh"
source "$1/deployment/installer/moonraker.sh"
source "$1/deployment/installer/moonraker-restart.sh"
PROJECT_NAME=test
TIMESTAMP=test
INSTALL_USER=printer
INSTALL_GROUP=printer
INSTALL_DIR=/home/biqu/KAI
KAI_GIT_ORIGIN=https://example.invalid/repo
KAI_GIT_PRIMARY_BRANCH=main
KAI_PRINTER_DATA_ROOT="$2"
KAI_MANAGED_CONFIG_DIR_PATH="$2/config/kai"
KAI_MOONRAKER_EXTENSION_CFG_PATH="$KAI_MANAGED_CONFIG_DIR_PATH/kai-moonraker.cfg"
KAI_LEGACY_MOONRAKER_EXTENSION_CFG_PATH="$2/config/kai-moonraker.cfg"
KAI_MOONRAKER_CONFIG_PATH="$2/config/moonraker.conf"
KAI_MOONRAKER_ALLOWED_SERVICES_PATH="$2/moonraker.asvc"
KAI_MOONRAKER_RESTART_MARKER="$2/pending/restart"
SERVICE_NAME=kai-agent
run_root() {
  local -a args=()
  while [[ "$#" -gt 0 ]]; do
    case "$1" in -o|-g) shift 2;; *) args+=("$1"); shift;; esac
  done
  "${args[@]}"
}
write_moonraker_extension_cfg
ensure_moonraker_include
ensure_moonraker_allowed_service
[[ "$KAI_MOONRAKER_RESTART_REQUIRED" == yes && -f "$KAI_MOONRAKER_RESTART_MARKER" ]]
rm "$KAI_MOONRAKER_RESTART_MARKER"
KAI_MOONRAKER_RESTART_REQUIRED=no
write_moonraker_extension_cfg
ensure_moonraker_include
ensure_moonraker_allowed_service
[[ "$KAI_MOONRAKER_RESTART_REQUIRED" == no && ! -e "$KAI_MOONRAKER_RESTART_MARKER" ]]
""",
        ROOT.as_posix(),
        tmp_path.as_posix(),
    )
    assert (config / "printer.cfg").read_text() == "[printer]\nkinematics: corexy\n"
    assert (config / "moonraker.conf").read_text().count("[include ") == 1
