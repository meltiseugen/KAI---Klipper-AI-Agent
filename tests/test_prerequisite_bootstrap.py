"""Bootstrap missing tools on disposable hosts; never run a host package manager."""

import sys
from pathlib import Path

import pytest

from tests.test_installer import ROOT, bash


@pytest.mark.parametrize("manager", ["apt-get", "opkg", "apk"])
def test_missing_bash_is_installed_before_reexec_and_index_is_reused(tmp_path, run_shell, manager):
    calls = tmp_path / "calls"
    bash(
        run_shell,
        """
set -euo pipefail
source "$1/deployment/installer/bootstrap.sh"
MANAGER="$2"
CALLS="$3"
HAS_BASH=no
uname() { echo Linux; }
bootstrap_is_creality() { return 1; }
bootstrap_command_path() {
  if [[ "$1" == bash ]]; then [[ "$HAS_BASH" == yes ]]; else [[ "$1" == "$MANAGER" ]]; fi
}
bootstrap_run_root() { printf '%s\\n' "$*" >> "$CALLS"; HAS_BASH=yes; }
bootstrap_bash
bootstrap_packages git
[[ "$HAS_BASH" == yes ]]
""",
        ROOT.as_posix(),
        manager,
        calls.as_posix(),
    )
    commands = calls.read_text().splitlines()
    install = "add" if manager == "apk" else "install"
    flags = " -y" if manager == "apt-get" else ""
    assert commands == [
        f"{manager} update",
        f"{manager} {install}{flags} bash",
        f"{manager} {install}{flags} git",
    ]


def test_help_and_check_do_not_install_even_when_bash_is_missing(tmp_path, run_shell):
    entry = tmp_path / "install.sh"
    entry.write_text((ROOT / "install.sh").read_text())
    modules = tmp_path / "deployment/installer"
    modules.mkdir(parents=True)
    (modules / "entware.sh").write_text("")
    marker = tmp_path / "mutated"
    (modules / "bootstrap.sh").write_text(
        (ROOT / "deployment/installer/bootstrap.sh").read_text()
        + "\nbootstrap_command_path() { return 1; }\n"
        + f'bootstrap_packages() {{ touch "{marker.as_posix()}"; return 99; }}\n'
    )
    assert "Usage:" in run_shell(entry.as_posix(), "--help").stdout
    result = run_shell(entry.as_posix(), "--check", check=False)
    assert result.returncode == 127
    assert "no packages were installed" in result.stderr
    assert not marker.exists()


def test_posix_entrypoint_installs_bash_then_runs_the_installer(tmp_path, run_shell, shell):
    entry = tmp_path / "install.sh"
    entry.write_text((ROOT / "install.sh").read_text(), newline="\n")
    modules = tmp_path / "deployment/installer"
    modules.mkdir(parents=True)
    (modules / "entware.sh").write_text("")
    bindir = tmp_path / "bin"
    bindir.mkdir()
    real_bash = Path(shell).with_name("bash.exe" if shell.endswith(".exe") else "bash")
    template = tmp_path / "fixture-bash"
    template.write_text(f'#!/bin/sh\nexec "{real_bash.as_posix()}" "$@"\n', newline="\n")
    template.chmod(0o755)
    calls = tmp_path / "calls"
    (modules / "bootstrap.sh").write_text(
        (ROOT / "deployment/installer/bootstrap.sh").read_text()
        + f"""
PATH="$(cd "{bindir.as_posix()}" && pwd):$PATH"
export PATH
bootstrap_command_path() {{
  if [ "$1" = bash ]; then [ -x "{bindir.as_posix()}/bash" ]; else command -v "$1"; fi
}}
uname() {{ echo Linux; }}
bootstrap_manager() {{ KLIPPERAI_PACKAGE_MANAGER=opkg; }}
bootstrap_run_root() {{
  printf '%s\\n' "$*" >> "{calls.as_posix()}"
  case "$*" in 'opkg install bash') cp "{template.as_posix()}" "{bindir.as_posix()}/bash";; esac
}}
""",
        newline="\n",
    )
    (modules / "modules.txt").write_text("phases\n", newline="\n")
    (modules / "phases.sh").write_text(
        f'preflight() {{ printf started >> "{calls.as_posix()}"; }}\n'
        + "\n".join(
            f"{name}() {{ :; }}"
            for name in (
                "configure_paths",
                "configure_options",
                "install_python_package",
                "install_service_configuration",
                "install_access_integrations",
                "print_next_steps",
            )
        )
        + "\n",
        newline="\n",
    )
    run_shell(entry.as_posix())
    assert calls.read_text().splitlines() == ["opkg update", "opkg install bash", "started"]


@pytest.mark.parametrize("existing", [True, False])
def test_creality_detection_selects_existing_or_bootstrapped_entware(tmp_path, run_shell, existing):
    vendor = tmp_path / "usr/data"
    (vendor / "printer_1_data").mkdir(parents=True)
    init = tmp_path / "etc/init.d"
    init.mkdir(parents=True)
    comm = tmp_path / "comm"
    comm.write_text("init\n")
    module = tmp_path / "bootstrap.sh"
    module.write_text(
        (ROOT / "deployment/installer/bootstrap.sh")
        .read_text()
        .replace("/usr/data", vendor.as_posix())
        .replace("/etc/init.d", init.as_posix())
        .replace("/proc/1/comm", comm.as_posix()),
        newline="\n",
    )
    result = run_shell(
        "-c",
        """
set -eu
. "$1"
EXISTING="$2"
bootstrap_command_path() {
  [ "$1" = opkg ] && [ "$EXISTING" = yes ]
}
bootstrap_entware() { echo bootstrapped; }
bootstrap_manager
printf '%s' "$KLIPPERAI_PACKAGE_MANAGER"
""",
        "test",
        module.as_posix(),
        "yes" if existing else "no",
    )
    assert result.stdout == ("opkg" if existing else "bootstrapped\nopkg")


@pytest.mark.parametrize("manager", ["opkg", "apt-get", "apk"])
def test_missing_prerequisites_are_installed_before_command_checks(tmp_path, run_shell, manager):
    calls = tmp_path / "calls"
    bash(
        run_shell,
        """
set -euo pipefail
source "$1/deployment/installer/prerequisites.sh"
source "$1/deployment/installer/preflight.sh"
SCRIPT_DIR="$1"
CALLS="$2"
MANAGER="$3"
READY=no
select_service_manager() { KLIPPERAI_SERVICE_MANAGER=appliance; }
require_linux() { :; }
bootstrap_opt_path() { :; }
bootstrap_manager() { KLIPPERAI_PACKAGE_MANAGER="$MANAGER"; }
bootstrap_command_path() { [[ "$READY" == yes || "$1" != git && "$1" != install && "$1" != stat ]]; }
prerequisite_git_https() { return 0; }
prerequisite_nginx_available() { return 0; }
prerequisite_python() { PREREQUISITE_PYTHON=fixture_python; [[ "$READY" == yes ]]; }
fixture_python() { [[ "$READY" == yes ]]; }
bootstrap_packages() { printf '%s\\n' "$*" >> "$CALLS"; READY=yes; }
require_cmd() { [[ "$READY" == yes ]]; printf 'required:%s\\n' "$1" >> "$CALLS"; }
log() { :; }
die() { echo "$*" >&2; exit 1; }
preflight
""",
        ROOT.as_posix(),
        calls.as_posix(),
        manager,
    )
    lines = calls.read_text().splitlines()
    assert "python3" in lines[0] and "git" in lines[0]
    assert "nginx" not in lines[0]  # Existing vendor nginx remains in place.
    assert lines.index("required:python3") > 0
    if manager == "opkg":
        assert all(
            package in lines[0]
            for package in (
                "git-http",
                "coreutils-install",
                "coreutils-stat",
                "python3-pip",
                "python3-openssl",
                "python3-sqlite3",
                "python3-ctypes",
            )
        )


def test_healthy_host_does_not_contact_package_repositories(run_shell):
    bash(
        run_shell,
        """
set -euo pipefail
source "$1/deployment/installer/prerequisites.sh"
bootstrap_opt_path() { :; }
bootstrap_command_path() { return 0; }
prerequisite_git_https() { return 0; }
prerequisite_nginx_available() { return 0; }
prerequisite_python() { PREREQUISITE_PYTHON=fixture_python; }
fixture_python() { return 0; }
bootstrap_manager() { echo unexpected-package-manager >&2; exit 1; }
bootstrap_packages() { echo unexpected-package-install >&2; exit 1; }
ensure_prerequisites
""",
        ROOT.as_posix(),
    )


def test_split_python_modules_are_repaired_automatically(tmp_path, run_shell):
    calls = tmp_path / "calls"
    bash(
        run_shell,
        """
set -euo pipefail
source "$1/deployment/installer/prerequisites.sh"
CALLS="$2"
READY=no
bootstrap_opt_path() { :; }
bootstrap_command_path() { return 0; }
prerequisite_git_https() { return 0; }
prerequisite_nginx_available() { return 0; }
prerequisite_python() { PREREQUISITE_PYTHON=fixture_python; }
fixture_python() { [[ "$READY" == yes ]]; }
bootstrap_manager() { KLIPPERAI_PACKAGE_MANAGER=opkg; }
bootstrap_packages() { printf '%s' "$*" > "$CALLS"; READY=yes; }
ensure_prerequisites
""",
        ROOT.as_posix(),
        calls.as_posix(),
    )
    text = calls.read_text()
    assert "python3-openssl" in text and "python3-sqlite3" in text and "ca-bundle" in text


@pytest.mark.parametrize("missing", ["certificates", "git-https"])
def test_partial_entware_install_gets_missing_https_support(tmp_path, run_shell, missing):
    calls = tmp_path / "calls"
    bash(
        run_shell,
        """
set -euo pipefail
source "$1/deployment/installer/prerequisites.sh"
CALLS="$2"
MISSING="$3"
READY=no
bootstrap_opt_path() { :; }
bootstrap_command_path() { return 0; }
prerequisite_nginx_available() { return 0; }
prerequisite_git_https() { [[ "$MISSING" != git-https || "$READY" == yes ]]; }
prerequisite_python() { PREREQUISITE_PYTHON=fixture_python; }
fixture_python() { [[ "$MISSING" != certificates || "$*" != *get_ca_certs* || "$READY" == yes ]]; }
bootstrap_manager() { KLIPPERAI_PACKAGE_MANAGER=opkg; }
bootstrap_packages() { printf '%s' "$*" > "$CALLS"; READY=yes; }
ensure_prerequisites
""",
        ROOT.as_posix(),
        calls.as_posix(),
        missing,
    )
    assert calls.read_text() == (
        "ca-certificates ca-bundle" if missing == "certificates" else "git-http ca-bundle"
    )


def test_entware_python_precedes_an_old_vendor_python(tmp_path, run_shell):
    opt = tmp_path / "opt/bin"
    opt.mkdir(parents=True)
    interpreter = opt / "python3"
    interpreter.write_text(f'#!/bin/sh\nexec "{sys.executable}" "$@"\n', newline="\n")
    interpreter.chmod(0o755)
    source = tmp_path / "prerequisites.sh"
    source.write_text(
        (ROOT / "deployment/installer/prerequisites.sh")
        .read_text()
        .replace("/opt/bin/", opt.as_posix() + "/")
    )
    result = bash(
        run_shell,
        """
source "$1"
bootstrap_command_path() { command -v "$1"; }
prerequisite_python
printf '%s' "$PREREQUISITE_PYTHON"
""",
        source.as_posix(),
    )
    assert result.stdout == interpreter.as_posix()


def test_virtualenv_helper_is_installed_locally_without_replacing_vendor_python(
    tmp_path, run_shell
):
    calls = tmp_path / "calls"
    bash(
        run_shell,
        """
set -euo pipefail
source "$1/deployment/installer/python.sh"
INSTALL_DIR="$2"
PYTHON_BIN=/opt/bin/python3
CALLS="$3"
run_as_user() {
  case "$*" in
    '/opt/bin/python3 -m venv --help'|'/opt/bin/python3 -m virtualenv --help') return 1;;
    '/opt/bin/python3 -m pip --version') return 0;;
    *) printf '%s\\n' "$*" >> "$CALLS";;
  esac
}
ensure_python_venv
[[ "$PYTHON_VENV_MODULE" == virtualenv-local ]]
create_python_virtual_environment
""",
        ROOT.as_posix(),
        tmp_path.as_posix(),
        calls.as_posix(),
    )
    text = calls.read_text()
    assert f"--target {tmp_path.as_posix()}/.local/installer-python" in text
    assert f"PYTHONPATH={tmp_path.as_posix()}/.local/installer-python" in text
    assert "--user" not in text and "--break-system-packages" not in text


@pytest.mark.parametrize("crypto_ready", [True, False])
def test_mips_crypto_build_tools_are_added_only_when_needed(tmp_path, run_shell, crypto_ready):
    calls = tmp_path / "calls"
    bash(
        run_shell,
        """
set -euo pipefail
source "$1/deployment/installer/prerequisites.sh"
KLIPPERAI_SERVICE_MANAGER=appliance
INSTALL_DIR=/usr/data/KlipperAI
PYTHON_BIN=/opt/bin/python3
READY="$2"
CALLS="$3"
uname() { echo mips; }
run_as_user() { [[ "$READY" == yes ]]; }
bootstrap_command_path() { return 1; }
bootstrap_manager() { KLIPPERAI_PACKAGE_MANAGER=opkg; }
bootstrap_packages() { printf '%s' "$*" > "$CALLS"; }
ensure_crypto_build_prerequisites
""",
        ROOT.as_posix(),
        "yes" if crypto_ready else "no",
        calls.as_posix(),
    )
    if crypto_ready:
        assert not calls.exists()
    else:
        assert calls.read_text() == "gcc make python3-dev"
