"""Real Bash routing on a disposable vendor filesystem; no host service mutations."""

import pytest

from tests.test_installer import ROOT, bash


@pytest.mark.parametrize(
    "kind,expected",
    [
        ("vendor", "appliance"),
        ("numbered", "appliance"),
        ("real-systemd", "systemd"),
        ("other", "systemd"),
    ],
)
def test_auto_detection_distinguishes_native_init_from_real_systemd(
    tmp_path, run_shell, kind, expected
):
    vendor = tmp_path / "usr/data" / ("printer_1_data" if kind == "numbered" else "printer_data")
    init = tmp_path / "etc/init.d"
    systemd = tmp_path / "run/systemd/system"
    comm = tmp_path / "proc/1/comm"
    comm.parent.mkdir(parents=True)
    comm.write_text("systemd\n" if kind == "real-systemd" else "init\n")
    if kind != "other":
        vendor.mkdir(parents=True)
        init.mkdir(parents=True)
    if kind == "real-systemd":
        systemd.mkdir(parents=True)
    source = (ROOT / "deployment/installer/platform.sh").read_text()
    for old, new in (
        ("/usr/data", vendor.parent),
        ("/etc/init.d", init),
        ("/run/systemd/system", systemd),
        ("/proc/1/comm", comm),
    ):
        source = source.replace(old, new.as_posix())
    module = tmp_path / "platform.sh"
    module.write_text(source)
    result = bash(
        run_shell,
        """
set -euo pipefail
source "$1"
id() { echo 0; }
die() { echo "$*" >&2; exit 1; }
select_service_manager
printf '%s' "$KLIPPERAI_SERVICE_MANAGER"
""",
        module.as_posix(),
    )
    assert result.stdout == expected


def test_native_preflight_does_not_require_any_systemd_command(tmp_path, run_shell):
    # Selection is tested above; here every required command passes except systemd tools.
    result = bash(
        run_shell,
        """
set -euo pipefail
source "$1/deployment/installer/preflight.sh"
select_service_manager() { KLIPPERAI_SERVICE_MANAGER=appliance; }
require_linux() { :; }
ensure_prerequisites() { :; }
require_cmd() { [[ "$1" != systemd* && "$1" != systemctl ]]; }
SCRIPT_DIR="$1"
log() { :; }
preflight
""",
        ROOT.as_posix(),
    )
    assert result.returncode == 0


def test_native_credential_setup_uses_stdin_and_native_cli_only(run_shell, tmp_path):
    calls = tmp_path / "calls"
    result = bash(
        run_shell,
        """
set -euo pipefail
source "$1/deployment/installer/platform.sh"
source "$1/deployment/installer/credentials.sh"
KLIPPERAI_SERVICE_MANAGER=appliance
INSTALL_DIR=/usr/data/KlipperAI
INSTALL_HOME=/root
KLIPPERAI_DATA_DIR=/usr/data/klipperai-data
KLIPPERAI_PRINTER_DATA_ROOT=/usr/data/printer_data
KLIPPERAI_CFG_PATH=/usr/data/printer_data/config/klipperai/klipperai.cfg
KLIPPERAI_LLM_PROVIDER=openai
KLIPPERAI_OPENAI_MODEL=selected-model
KLIPPERAI_OPENAI_API_KEY=never-print-this-key
CALLS="$2"
log() { :; }
sanitize_legacy_environment_files() { :; }
run_as_user() {
  [[ "$*" != *never-print-this-key* ]]
  local secret
  IFS= read -r secret || [[ -n "$secret" ]]
  [[ "$secret" == never-print-this-key ]]
  printf '%s\\n' "$*" >> "$CALLS"
}
install_encrypted_credentials
[[ -z "${KLIPPERAI_OPENAI_API_KEY+x}" ]]
""",
        ROOT.as_posix(),
        calls.as_posix(),
    )
    text = calls.read_text()
    assert "deployment.appliance_install" in text
    assert "systemd" not in text
    assert "never-print-this-key" not in text + result.stdout + result.stderr


def test_native_access_setup_starts_only_the_application_init_service(run_shell):
    result = bash(
        run_shell,
        """
set -euo pipefail
source "$1/deployment/installer/install-access-integrations.sh"
KLIPPERAI_SERVICE_MANAGER=appliance
INSTALL_MAINSAIL_NAV=no
INSTALL_OCTOEVERYWHERE_PATCH=no
INSTALL_OCTOEVERYWHERE_AUTO_REAPPLY=no
log() { :; }
run_root() { echo 'unexpected service operation'; exit 1; }
start_appliance_service() { echo native-start; }
install_access_integrations
""",
        ROOT.as_posix(),
    )
    assert result.stdout.strip() == "native-start"


def test_native_uninstall_dispatches_without_systemd_or_printer_controls(run_shell, tmp_path):
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    result = bash(
        run_shell,
        """
set -euo pipefail
source "$1/uninstall.sh"
KLIPPERAI_SERVICE_MANAGER=appliance
KLIPPERAI_PROJECT_CHECKOUT_PATH="$2"
PURGE_CREDENTIALS=yes
run_root() { printf '%s\\n' "$*"; }
remove_agent_service
""",
        ROOT.as_posix(),
        checkout.as_posix(),
    )
    assert "deployment.appliance_uninstall" in result.stdout
    assert "--purge-credentials" in result.stdout
    assert "systemctl" not in result.stdout


def test_uninstall_reuses_vendor_proxy_reload_instead_of_systemd(run_shell, tmp_path):
    module = tmp_path / "deployment/installer/nginx.sh"
    module.parent.mkdir(parents=True)
    module.write_text("reload_nginx() { printf '%s' vendor-config-validated-and-reloaded; }\n")
    result = bash(
        run_shell,
        """
source "$1/uninstall.sh"
KLIPPERAI_PROJECT_CHECKOUT_PATH="$2"
run_root() { echo unexpected-system-service-command; exit 1; }
reload_nginx
""",
        ROOT.as_posix(),
        tmp_path.as_posix(),
    )
    assert result.stdout == "vendor-config-validated-and-reloaded"
