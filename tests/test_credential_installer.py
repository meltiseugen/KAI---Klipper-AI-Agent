import pytest

from tests.test_installer import ROOT, bash


@pytest.mark.parametrize("tpm", [True, False])
def test_secure_installer_uses_stdin_encrypted_master_and_sanitizes_all_env_copies(
    tmp_path, run_shell, shell_env, tpm
):
    config = tmp_path / "etc/kai"
    config.mkdir(parents=True)
    (config / "kai.env").write_text('KAI_OPENAI_API_KEY="old-secret"\nKEEP=metadata\n')
    (config / "kai.env.bak.old").write_text('OPENAI_API_KEY="obsolete-secret"\nKEEP=backup\n')
    module = tmp_path / "credentials.sh"
    module.write_text(
        (ROOT / "deployment/installer/credentials.sh")
        .read_text()
        .replace("/etc/kai", config.as_posix())
    )
    fake = tmp_path / "bin"
    fake.mkdir()
    (fake / "systemd-creds").write_text(
        '#!/bin/sh\ncat >/dev/null\nprintf "encrypted-master-ciphertext"\n', newline="\n"
    )
    (fake / "systemd-creds").chmod(0o755)
    calls = tmp_path / "calls"
    script = """
set -euo pipefail
source "$1/deployment/installer/common.sh"
source "$2"
PROJECT_NAME=test
CALLS="$3"
INSTALL_USER=printer
INSTALL_HOME="$4/home"
INSTALL_DIR="$1"
KAI_DATA_DIR="$4/data"
KAI_PRINTER_DATA_ROOT="$4/printer"
KAI_CFG_PATH="$4/printer/kai.cfg"
KAI_LLM_PROVIDER=openai
KAI_OPENAI_MODEL=selected-model
KAI_OPENAI_API_KEY=private-input-key
SERVICE_NAME=kai-agent
TPM="$5"
fake_bin="$4/bin"
if command -v cygpath >/dev/null; then fake_bin="$(cygpath -u "$fake_bin")"; fi
export PATH="$fake_bin:$PATH"
systemctl() { return 0; }
run_root() {
  printf '%s\n' "$*" >>"$CALLS"
  case "$1" in
    install) if [[ "$2" == -d ]]; then mkdir -p "${@: -1}"; else cp "${@: -2:1}" "${@: -1}"; fi ;;
    chown) : ;;
    systemd-creds) [[ "$TPM" == yes ]] ;;
    systemctl) : ;;
    systemd-run)
      local secret
      IFS= read -r secret || [[ -n "$secret" ]]
      [[ "$secret" == private-input-key ]]
      [[ "$*" != *private-input-key* ]]
      ;;
    *) "$@" ;;
  esac
}
install_encrypted_credentials
[[ -z "${KAI_OPENAI_API_KEY+x}" ]]
KAI_OPENAI_API_KEY=private-input-key
install_encrypted_credentials
"""
    result = bash(
        run_shell,
        script,
        ROOT.as_posix(),
        module.as_posix(),
        calls.as_posix(),
        tmp_path.as_posix(),
        "yes" if tpm else "no",
    )
    master = config / "credentials/provider-master.cred"
    assert master.read_text() == "encrypted-master-ciphertext"
    assert not list(master.parent.glob(".master.*"))
    assert (config / "kai.env").read_text() == "KEEP=metadata\n"
    assert (config / "kai.env.bak.old").read_text() == "KEEP=backup\n"
    text = calls.read_text()
    assert "LoadCredentialEncrypted=kai-provider-master:" in text
    assert "systemctl stop kai-agent" in text
    assert ("host+tpm2" in text) == tpm
    assert text.count("head -c 32 /dev/urandom") == 1
    assert "private-input-key" not in text + result.stdout + result.stderr
    assert "old-secret" not in text + result.stdout + result.stderr
    if not tpm:
        assert "complete disk image" in result.stderr


def test_uninstall_purge_removes_only_credential_artifacts(tmp_path, run_shell):
    # Source definitions only; no actual uninstall entrypoint or host paths are executed.
    source = (ROOT / "uninstall.sh").read_text().rsplit('\nmain "$@"', 1)[0]
    config = tmp_path / "etc/kai"
    module = tmp_path / "uninstall-functions.sh"
    module.write_text(source.replace("/etc/kai", config.as_posix()))
    data = tmp_path / "data"
    home = tmp_path / "home"
    configured = tmp_path / "configured-private"
    files = [
        data / "private/providers.sqlite3",
        configured / "providers.sqlite3",
        home / ".config/kai/providers.sqlite3",
        config / "credentials/provider-master.cred",
        config / "kai.env.bak.old",
    ]
    for path in files:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("private")
    history = data / "investigations.sqlite3"
    history.write_text("keep-history")
    bash(
        run_shell,
        """
source "$1"
KAI_DATA_DIR="$2"
KAI_SERVICE_HOME="$3"
KAI_PROVIDER_STORAGE_DIR="$4"
if command -v cygpath >/dev/null; then
  KAI_DATA_DIR="$(cygpath -u "$KAI_DATA_DIR")"
  KAI_SERVICE_HOME="$(cygpath -u "$KAI_SERVICE_HOME")"
  KAI_PROVIDER_STORAGE_DIR="$(cygpath -u "$KAI_PROVIDER_STORAGE_DIR")"
fi
run_root() { "$@"; }
purge_provider_credentials
""",
        module.as_posix(),
        data.as_posix(),
        home.as_posix(),
        configured.as_posix(),
    )
    assert all(not path.exists() for path in files)
    assert history.read_text() == "keep-history"
