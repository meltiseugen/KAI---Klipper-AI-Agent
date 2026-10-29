"""Preserve vendor-layout workarounds without claiming native KE service support."""

from pathlib import Path

import pytest

from deployment import update
from tests.test_installer import ROOT, bash


@pytest.fixture
def vendor_layout(tmp_path):
    vendor = tmp_path / "usr/data"
    home = tmp_path / "home/printer"
    home.mkdir(parents=True)
    module = tmp_path / "discovery.sh"
    module.write_text(
        (ROOT / "deployment/installer/discovery.sh")
        .read_text()
        .replace("/usr/data", vendor.as_posix())
        .replace("/etc/nginx", (tmp_path / "etc/nginx").as_posix())
    )
    return module, vendor, home


@pytest.mark.parametrize(
    "directory", ["printer_data", "printer_1_data", "printer_2_data", "printer_3_data"]
)
def test_vendor_printer_data_precedes_home_layout(vendor_layout, run_shell, directory):
    module, vendor, home = vendor_layout
    expected = vendor / directory
    expected.mkdir(parents=True)
    (home / "printer_data").mkdir()
    result = bash(
        run_shell, 'source "$1"; detect_printer_data_root "$2"', module.as_posix(), home.as_posix()
    )
    assert result.stdout == expected.as_posix()


def test_vendor_moonraker_fallback_preserves_explicit_config(vendor_layout, tmp_path, run_shell):
    module, vendor, home = vendor_layout
    config = vendor / "printer_data/config"
    config.mkdir(parents=True)
    (config / "moonraker.conf").write_text("[server]\n")
    explicit = tmp_path / "explicit"
    script = 'source "$1"; detect_moonraker_config_path "$2" "$3"'
    result = bash(run_shell, script, module.as_posix(), home.as_posix(), explicit.as_posix())
    assert result.stdout == (config / "moonraker.conf").as_posix()
    explicit.mkdir()
    (explicit / "moonraker.conf").write_text("[server]\n")
    result = bash(run_shell, script, module.as_posix(), home.as_posix(), explicit.as_posix())
    assert result.stdout == (explicit / "moonraker.conf").as_posix()


@pytest.mark.parametrize(
    "relative",
    [
        "conf.d/mainsail.conf",
        "conf.d/default.conf",
        "nginx.conf",
        "conf/nginx.conf",
        "vendor/custom.conf",
    ],
)
def test_vendor_nginx_candidates_and_fallback_search(vendor_layout, run_shell, relative):
    module, vendor, _ = vendor_layout
    config = vendor / "nginx" / relative
    config.parent.mkdir(parents=True)
    config.write_text("server {\n    listen 4409;\n}\n")
    result = bash(run_shell, 'source "$1"; detect_nginx_server_block_path', module.as_posix())
    assert result.stdout == config.as_posix()


@pytest.mark.parametrize("directory", ["octoeverywhere", "OctoEverywhere"])
def test_vendor_octoeverywhere_checkout_is_discovered(vendor_layout, run_shell, directory):
    module, vendor, home = vendor_layout
    script = vendor / directory / "moonraker_octoeverywhere/static/oe-ui.js"
    script.parent.mkdir(parents=True)
    script.touch()
    result = bash(
        run_shell,
        'source "$1"; detect_octoeverywhere_root "$2"',
        module.as_posix(),
        home.as_posix(),
    )
    assert Path(result.stdout).resolve() == (vendor / directory).resolve()


@pytest.mark.parametrize("valid", [True, False])
def test_vendor_nginx_reload_uses_active_binary_and_config(tmp_path, run_shell, valid):
    proc = tmp_path / "proc/123"
    proc.mkdir(parents=True)
    config = tmp_path / "usr/data/nginx/nginx.conf"
    config.parent.mkdir(parents=True)
    config.touch()
    (proc / "cmdline").write_bytes(
        f"nginx: master process /vendor/nginx -c {config.as_posix()}".encode() + b"\0"
    )
    binary = tmp_path / "nginx"
    binary.write_text("#!/bin/sh\nexit 0\n", newline="\n")
    binary.chmod(0o755)
    module = tmp_path / "nginx.sh"
    module.write_text(
        (ROOT / "deployment/installer/nginx.sh")
        .read_text()
        .replace("/proc/", (tmp_path / "proc").as_posix() + "/")
    )
    calls = tmp_path / "calls"
    bash(
        run_shell,
        """
set -euo pipefail
source "$1"
CALLS="$2"
BINARY="$3"
VALID="$4"
pidof() { echo 123; }
readlink() { printf '%s' "$BINARY"; }
run_root() {
  printf '%s\\n' "$*" >> "$CALLS"
  if [[ "$2" == -t ]]; then [[ "$VALID" == yes ]]; else return 0; fi
}
if reload_nginx; then [[ "$VALID" == yes ]]; else [[ "$VALID" == no ]]; fi
""",
        module.as_posix(),
        calls.as_posix(),
        binary.as_posix(),
        "yes" if valid else "no",
    )
    expected = [f"{binary.as_posix()} -t -c {config.as_posix()}"]
    if valid:
        expected.append(f"{binary.as_posix()} -s reload -c {config.as_posix()}")
    assert calls.read_text().splitlines() == expected


def test_python_without_stdlib_venv_uses_virtualenv(tmp_path, run_shell):
    calls = tmp_path / "calls"
    result = bash(
        run_shell,
        """
set -euo pipefail
source "$1/deployment/installer/python.sh"
PYTHON_BIN=vendor-python
INSTALL_DIR="$2/checkout"
CALLS="$2/calls"
run_as_user() {
  if [[ "$*" == 'vendor-python -m venv --help' ]]; then return 1; fi
  if [[ "$*" == 'vendor-python -m virtualenv --help' ]]; then return 0; fi
  printf '%s\\n' "$*" >> "$CALLS"
}
ensure_python_venv
[[ "$PYTHON_VENV_MODULE" == virtualenv ]]
create_python_virtual_environment
""",
        ROOT.as_posix(),
        tmp_path.as_posix(),
    )
    assert result.returncode == 0
    assert (
        calls.read_text().strip()
        == f"vendor-python -m virtualenv {tmp_path.as_posix()}/checkout/.venv"
    )


@pytest.mark.parametrize("version,success", [(249, False), (250, True)])
def test_credential_preflight_requires_real_supported_systemd(
    tmp_path, run_shell, version, success
):
    for name, body in (
        ("systemd-creds", f"printf 'systemd {version}\\n'"),
        ("systemd-run", "exit 99"),
    ):
        program = tmp_path / "shell-bin" / name
        program.write_text("#!/bin/sh\n" + body + "\n", newline="\n")
        program.chmod(0o755)
    result = run_shell(
        "-c",
        """
set -euo pipefail
source "$1/deployment/installer/common.sh"
source "$1/deployment/installer/platform.sh"
source "$1/deployment/installer/preflight.sh"
PROJECT_NAME=test
SCRIPT_DIR="$1"
require_linux() { :; }
ensure_prerequisites() { :; }
preflight
""",
        "test",
        ROOT.as_posix(),
        str(version),
        check=False,
    )
    assert (result.returncode == 0) is success
    if not success:
        assert "systemd 250 or newer" in result.stderr


def test_root_service_account_remains_an_explicit_install_blocker(run_shell):
    result = run_shell(
        "-c",
        """
set -euo pipefail
source "$1/deployment/installer/common.sh"
source "$1/deployment/installer/configure-paths.sh"
PROJECT_NAME=test
detect_default_install_user() { echo root; }
prompt_default() { printf '%s' "$2"; }
id() { if [[ "${1:-}" == -u ]]; then echo 0; fi; }
configure_paths
""",
        "test",
        ROOT.as_posix(),
        check=False,
    )
    assert result.returncode != 0
    assert "unprivileged service account" in result.stderr


def test_root_ssh_update_is_blocked_before_any_host_mutation(monkeypatch):
    monkeypatch.setattr(
        update.sys, "argv", ["update", "--install-dir", "/usr/data/KlipperAI", "--rollback"]
    )
    monkeypatch.setattr(update.sys, "platform", "linux")
    monkeypatch.setattr(update.os, "geteuid", lambda: 0, raising=False)
    monkeypatch.setattr(
        update.subprocess,
        "check_output",
        lambda *a, **k: pytest.fail("must reject before service I/O"),
    )
    with pytest.raises(SystemExit) as error:
        update.main()
    assert error.value.code == 2
