"""Old systemd keeps authenticated encryption and an unprivileged application."""

import os
import socket
import struct
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from deployment import systemd_legacy as helper
from deployment import systemd_legacy_install as installer
from deployment.appliance_credentials import HostCredentials
from tests.test_installer import ROOT, bash


@pytest.fixture
def wrapped(tmp_path):
    store = HostCredentials(tmp_path / "host/key", tmp_path / "encrypted/master.enc")
    store.provision()
    return store


def connection(uid=0):
    return SimpleNamespace(
        getsockopt=Mock(return_value=struct.pack("3i", 1, uid, 0)), sendall=Mock()
    )


def test_socket_sends_only_authenticated_master_to_root(wrapped, monkeypatch):
    monkeypatch.setattr(socket, "SO_PEERCRED", 17, raising=False)
    client = connection()
    helper.serve(client, wrapped)
    client.getsockopt.assert_called_once_with(socket.SOL_SOCKET, socket.SO_PEERCRED, 12)
    client.sendall.assert_called_once_with(wrapped.master())
    original = wrapped.wrapped_master.read_bytes()
    wrapped.wrapped_master.write_bytes(original[:-1] + bytes([original[-1] ^ 1]))
    tampered = wrapped.wrapped_master.read_bytes()
    client.sendall.reset_mock()
    with pytest.raises(ValueError, match="authentication"):
        helper.serve(client, wrapped)
    client.sendall.assert_not_called()
    assert wrapped.wrapped_master.read_bytes() == tampered


def test_socket_refuses_unprivileged_peers_without_reading_master(monkeypatch):
    monkeypatch.setattr(socket, "SO_PEERCRED", 17, raising=False)
    client = connection(1000)
    credentials = SimpleNamespace(master=Mock(side_effect=AssertionError("must not read")))
    with pytest.raises(ValueError, match="service manager"):
        helper.serve(client, credentials)
    credentials.master.assert_not_called()
    client.sendall.assert_not_called()


def test_helper_cli_provision_reuses_ciphertext_and_hides_errors(wrapped, monkeypatch, capsys):
    monkeypatch.setattr(helper, "HOST_KEY", wrapped.host_key)
    monkeypatch.setattr(helper, "WRAPPED_MASTER", wrapped.wrapped_master)
    monkeypatch.setattr(helper, "protect_process", Mock())
    monkeypatch.setattr(helper, "os", SimpleNamespace(name="posix", geteuid=lambda: 0))
    original = wrapped.wrapped_master.read_bytes()
    helper.main(["provision"])
    assert wrapped.wrapped_master.read_bytes() == original
    wrapped.host_key.unlink()
    with pytest.raises(SystemExit) as failure:
        helper.main(["provision"])
    assert failure.value.code == 1
    assert not wrapped.host_key.exists()
    assert wrapped.wrapped_master.read_bytes() == original
    output = capsys.readouterr()
    assert output.out == "" and "original data kept" in output.err


def test_helper_requires_root_and_accepts_only_fixed_operations(monkeypatch):
    monkeypatch.setattr(helper, "os", SimpleNamespace(name="posix", geteuid=lambda: 1000))
    with pytest.raises(SystemExit) as failure:
        helper.main(["serve"])
    assert failure.value.code == 2
    with pytest.raises(SystemExit):
        helper.main(["serve", "--file", "/etc/shadow"])


def test_units_use_root_owned_isolated_helper_and_socket_only():
    units = installer.units(Path("/usr/local/bin/python3.10"), helper.LIBRARY)
    listener = units[helper.SOCKET_UNIT]
    service = units[helper.SERVICE_UNIT]
    assert "SocketMode=0600" in listener and "SocketUser=root" in listener
    assert "Accept=yes" in listener and "RemoveOnStop=yes" in listener
    assert "-I /usr/local/lib/kai-credentials/runner.py serve" in service
    assert "StandardOutput=socket" in service and "LimitCORE=0" in service
    assert "ProtectHome=yes" in service and "ProtectSystem=strict" in service
    assert "klipper.service" not in service and "moonraker.service" not in service
    assert "PYTHONPATH" not in service and ".venv" not in service
    with pytest.raises(ValueError, match="plain absolute"):
        installer.units(Path("/home/a b/python"), helper.LIBRARY)


def test_copying_helper_refuses_redirects_and_hardlinks(tmp_path, monkeypatch):
    # Root ownership is tested separately; CI's disposable paths are user-owned.
    monkeypatch.setattr(installer, "trusted_path", Mock())
    source = tmp_path / "source"
    source.write_bytes(b"safe helper")
    target = tmp_path / "target"
    installer.copy_file(source, target)
    original = target.read_bytes()
    hardlink = tmp_path / "linked"
    os.link(target, hardlink)
    with pytest.raises(ValueError, match="singly linked"):
        installer.copy_file(source, target)
    assert target.read_bytes() == original
    hardlink.unlink()
    installer.copy_file(source, target)


def test_root_helper_cannot_execute_user_owned_code(tmp_path, monkeypatch):
    path = tmp_path / "helper.py"
    path.write_text("content")
    original = Path.lstat

    def metadata(p):
        if p == path:
            return SimpleNamespace(st_uid=1000, st_mode=0o100600)
        return original(p)

    monkeypatch.setattr(Path, "lstat", metadata)
    monkeypatch.setattr(installer, "os", SimpleNamespace(name="posix"))
    with pytest.raises(ValueError, match="root-owned"):
        installer.trusted_path(path)


def test_install_snapshots_crypto_in_private_root_helper(tmp_path, monkeypatch):
    library = tmp_path / "library"
    units = tmp_path / "units"
    units.mkdir()
    package = tmp_path / "crypto"
    package.mkdir()
    (package / "__init__.py").write_text("crypto")
    (package / "__pycache__").mkdir()
    (package / "__pycache__/old.pyc").write_bytes(b"ignored")
    monkeypatch.setattr(
        installer, "Cryptodome", SimpleNamespace(__file__=str(package / "__init__.py"))
    )
    monkeypatch.setattr(installer, "trusted_path", Mock())
    monkeypatch.setattr(
        installer, "private_directory", lambda p: p.mkdir(mode=0o700, exist_ok=True)
    )
    monkeypatch.setattr(installer.sys, "_base_executable", "/usr/local/bin/python3.10")
    monkeypatch.setattr(helper, "WRAPPED_MASTER", tmp_path / "state/master.enc")
    execute = Mock()
    monkeypatch.setattr(installer.subprocess, "run", execute)
    # Windows cannot render a POSIX absolute path through its native Path class.
    monkeypatch.setattr(installer, "units", lambda python, root: {"socket": "fixture unit"})
    installer.install(library, units)
    installer.install(library, units)
    assert not (library / "Cryptodome/__pycache__").exists()
    assert (library / "deployment/systemd_legacy.py").read_bytes() == Path(
        helper.__file__
    ).read_bytes()
    assert (units / "socket").read_text() == "fixture unit"
    command = execute.call_args.args[0]
    assert command[-1] == "provision" and command[1] == "-I"
    assert str(library / "runner.py") in command
    (tmp_path / "state").mkdir()
    (tmp_path / "state/provider-master.cred").write_bytes(b"preserve-modern-master")
    with pytest.raises(ValueError, match="existing systemd"):
        installer.install(library, units)
    assert (tmp_path / "state/provider-master.cred").read_bytes() == b"preserve-modern-master"


def test_legacy_app_unit_uses_systemd_credentials_without_root_agent(tmp_path, run_shell):
    target = tmp_path / "unit"
    bash(
        run_shell,
        """
set -euo pipefail
source "$1/deployment/installer/service.sh"
INSTALL_USER=biqu
INSTALL_DIR=/home/biqu/KAI
KAI_CREDENTIAL_BACKEND=legacy-systemd
SERVICE_NAME=kai-agent
TARGET="$2"
backup_file() { :; }
run_root() { if [[ "$2" != -d ]]; then cp "${@: -2:1}" "$TARGET"; fi; }
write_systemd_service
""",
        ROOT.as_posix(),
        target.as_posix(),
    )
    text = target.read_text()
    assert "User=biqu" in text
    assert "Requires=kai-credentials.socket" in text
    assert "LoadCredential=kai-provider-master:/run/kai-credentials.sock" in text
    assert "LoadCredentialEncrypted" not in text and "ExecStartPre=" not in text


def test_legacy_installer_sends_provider_key_only_over_stdin(tmp_path, run_shell):
    calls = tmp_path / "calls"
    result = bash(
        run_shell,
        """
set -euo pipefail
source "$1/deployment/installer/legacy-credentials.sh"
CALLS="$2"
INSTALL_HOME=/home/biqu
INSTALL_USER=biqu
INSTALL_DIR=/home/biqu/KAI
KAI_DATA_DIR=/var/lib/kai
KAI_CFG_PATH=/home/biqu/printer_data/config/kai/kai.cfg
KAI_PRINTER_DATA_ROOT=/home/biqu/printer_data
KAI_LLM_PROVIDER=openai
KAI_OPENAI_MODEL=selected
KAI_OPENAI_API_KEY=test-private-secret
SERVICE_NAME=kai-agent
warn() { :; }
sanitize_legacy_environment_files() { echo sanitized >> "$CALLS"; }
systemctl() { return 0; }
run_root() {
  printf '%s\\n' "$*" >> "$CALLS"
  if [[ "$1" == systemd-run ]]; then
    local secret
    IFS= read -r secret || [[ -n "$secret" ]]
    [[ "$secret" == test-private-secret ]]
  fi
}
install_legacy_systemd_credentials
[[ -z "${KAI_OPENAI_API_KEY+x}" ]]
""",
        ROOT.as_posix(),
        calls.as_posix(),
    )
    text = calls.read_text()
    assert "LoadCredential=kai-provider-master:/run/kai-credentials.sock" in text
    assert "deployment.systemd_legacy_install" in text
    assert "User=biqu" in text and "sanitized" in text
    assert "test-private-secret" not in text + result.stdout + result.stderr
    assert "systemctl stop kai-agent" in text
    assert "systemctl restart moonraker" not in text
