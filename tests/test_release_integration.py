"""Real installer output booted as a daemon; all host paths are disposable."""

import json
import shlex

from tests.release_helpers import ROOT, daemon, free_port, http
from tests.test_installer import bash


def test_generated_environment_config_and_unit_boot_without_touching_printer(tmp_path, run_shell):
    etc = tmp_path / "etc"
    etc.mkdir()
    config = tmp_path / "printer/config"
    config.mkdir(parents=True)
    printer = config / "printer.cfg"
    printer.write_bytes(b"[printer]\nkinematics: cartesian\n")
    original = printer.read_bytes()
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    (checkout / "pyproject.toml").write_text('[project]\nname="klipperai"\n')
    (checkout / ".git").mkdir()
    (config / "moonraker.conf").write_text("[server]\n")
    for name in ("settings", "service"):
        (tmp_path / f"{name}.sh").write_text(
            (ROOT / f"deployment/installer/{name}.sh")
            .read_text()
            .replace("/etc/klipperai", etc.as_posix())
            .replace("/etc/systemd/system", etc.as_posix())
        )
    port = free_port()
    bash(
        run_shell,
        """
set -euo pipefail
source "$1/deployment/installer/common.sh"
source "$1/deployment/installer/configure-paths.sh"
source "$1/deployment/installer/configure-options.sh"
source "$2/settings.sh"
source "$2/service.sh"
TEST_ROOT="$2"
TEST_PORT="$3"
PROJECT_NAME=integration
TIMESTAMP=test
SERVICE_NAME=klipperai-agent
detect_default_install_user() { echo printer; }
id() { if [[ "${1:-}" == -u ]]; then echo 1000; fi; }
home_for_user() { echo "$TEST_ROOT"; }
group_for_user() { echo printer; }
detect_printer_data_root() { echo "$TEST_ROOT/printer"; }
detect_moonraker_config_path() { echo "$TEST_ROOT/printer/config/moonraker.conf"; }
detect_git_origin() { echo https://example.invalid/klipperai; }
detect_git_primary_branch() { echo main; }
detect_octoeverywhere_root() { :; }
detect_octoeverywhere_service_name() { :; }
detect_nginx_server_block_path() { echo "$TEST_ROOT/etc/nginx.conf"; }
run_as_user() { "$@"; }
prompt_default() {
  case "$1" in
    'Project checkout path to install from') echo "$TEST_ROOT/checkout";;
    'Local KlipperAI data directory') echo "$TEST_ROOT/app-data";;
    'Local KlipperAI bind port') echo "$TEST_PORT";;
    'Moonraker URL') echo http://127.0.0.1:1;;
    *) printf '%s' "$2";;
  esac
}
prompt_secret() { printf '%s' 'test-key-must-never-be-written'; }
confirm() { [[ "$1" == 'Proceed with installation?' ]]; }
print_summary() { :; }
# Execute real configuration phases. Only ownership flags require a host substitute.
run_root() {
  local -a args=()
  while [[ "$#" -gt 0 ]]; do
    case "$1" in -o|-g) shift 2;; *) args+=("$1"); shift;; esac
  done
  "${args[@]}"
}
configure_paths
configure_options
write_env_file
write_cfg_file
write_systemd_service
""",
        ROOT.as_posix(),
        tmp_path.as_posix(),
        str(port),
    )
    env = etc / "klipperai.env"
    cfg = config / "klipperai/klipperai.cfg"
    unit = (etc / "klipperai-agent.service").read_text()
    assert f"WorkingDirectory={checkout.as_posix()}" in unit
    assert f"EnvironmentFile=-{env.as_posix()}" in unit
    assert f"ExecStart={checkout.as_posix()}/.venv/bin/klipperai-agent" in unit
    assert "LoadCredentialEncrypted=klipperai-provider-master:" in unit
    assert "enable_write_actions: false" in cfg.read_text()
    assert "test-key-must-never-be-written" not in env.read_text() + cfg.read_text() + unit
    generated = dict(shlex.split(line)[0].split("=", 1) for line in env.read_text().splitlines())
    generated["KLIPPERAI_PORT"] = str(port)
    with daemon(tmp_path, generated) as base:
        with http(base, "/") as response:
            assert b'data-api-base="/klipperai/api"' in response.read()
        with http(base, "/api/ui-sessions", {}) as response:
            session = json.load(response)["session_id"]
        with http(base, "/api/bootstrap?session_id=" + session) as response:
            assert json.load(response)["provider_configured"] is False
    assert printer.read_bytes() == original


def test_uninstall_removes_code_selector_but_preserves_other_dropins(tmp_path, run_shell):
    unit = tmp_path / "klipperai-agent.service"
    unit.write_text("managed unit")
    dropins = tmp_path / "klipperai-agent.service.d"
    dropins.mkdir()
    selector = dropins / "50-klipperai-release.conf"
    selector.write_text("managed code selector")
    override = dropins / "90-operator.conf"
    override.write_text("operator settings to preserve")
    commands = tmp_path / "commands"
    script = """
set -euo pipefail
source "$1/uninstall.sh"
SYSTEMD_UNIT_PATH="$2"
COMMANDS="$3"
systemctl() { printf '%s\\n' "$*" >> "$COMMANDS"; }
run_root() { "$@"; }
remove_agent_service
"""
    for _ in range(2):
        bash(run_shell, script, ROOT.as_posix(), unit.as_posix(), commands.as_posix())
    assert not unit.exists() and not selector.exists()
    assert override.read_text() == "operator settings to preserve"
    assert (
        commands.read_text().splitlines()
        == ["list-unit-files klipperai-agent", "disable --now klipperai-agent", "daemon-reload"] * 2
    )
