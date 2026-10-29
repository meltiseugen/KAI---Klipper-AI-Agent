from tests.test_installer import ROOT, bash


def test_rendered_service_keeps_host_access_and_uses_private_umask(tmp_path, run_shell):
    output = tmp_path / "service"
    bash(
        run_shell,
        """
set -euo pipefail
source "$1/deployment/installer/service.sh"
OUTPUT="$2"
SERVICE_NAME=klipperai
INSTALL_USER=printer
INSTALL_DIR=/home/printer/KlipperAI
backup_file() { :; }
run_root() {
  [[ "$1" == install ]] || return 1
  [[ "$2" == -d ]] && return 0
  cp "${@: -2:1}" "$OUTPUT"
}
write_systemd_service
""",
        ROOT.as_posix(),
        output.as_posix(),
    )
    text = output.read_text()
    example = (ROOT / "deployment/systemd/klipperai-agent.service").read_text()
    for setting in (
        "UMask=0077",
        "NoNewPrivileges=yes",
        "PrivateTmp=yes",
        "Environment=PYTHONDONTWRITEBYTECODE=1",
    ):
        assert setting in text and setting in example
    assert "User=printer" in text
    for restriction in ("ProtectSystem=", "ProtectHome=", "PrivateDevices=", "ReadWritePaths="):
        assert restriction not in text and restriction not in example


def test_environment_file_and_backups_use_private_install_modes(tmp_path, run_shell):
    # Redirect every absolute installation path before executing the module.
    target = tmp_path / "etc"
    target.mkdir()
    env_file = target / "klipperai.env"
    backup = target / "klipperai.env.bak.test"
    env_file.write_text("old-private-key")
    backup.write_text("previous-backup")
    module = tmp_path / "settings.sh"
    module.write_text(
        (ROOT / "deployment/installer/settings.sh")
        .read_text()
        .replace("/etc/klipperai", target.as_posix())
    )
    commands = tmp_path / "commands"
    result = bash(
        run_shell,
        """
set -eo pipefail
source "$1/deployment/installer/common.sh"
source "$2"
COMMANDS="$3"
TIMESTAMP=test
KLIPPERAI_OPENAI_API_KEY=new-private-key
    KLIPPERAI_DATA_DIR=/var/lib/klipperai
log() { :; }
run_root() { printf '%s\n' "$*" >> "$COMMANDS"; "$@"; }
write_env_file
""",
        ROOT.as_posix(),
        module.as_posix(),
        commands.as_posix(),
    )
    calls = commands.read_text().splitlines()
    assert calls[1] == f"chmod 600 {env_file.as_posix()}"
    assert calls[2] == f"install -m 600 {env_file.as_posix()} {backup.as_posix()}"
    assert calls[3].startswith("install -m 600 ") and calls[3].endswith(env_file.as_posix())
    assert backup.read_text() == "old-private-key"
    assert "new-private-key" not in env_file.read_text()
    assert 'KLIPPERAI_PROVIDER_STORAGE_DIR="/var/lib/klipperai/private"' in env_file.read_text()
    assert "private-key" not in result.stdout + result.stderr + commands.read_text()


def test_install_data_mode_and_nginx_template():
    install = (ROOT / "deployment/installer/install-python-package.sh").read_text()
    assert 'install -d -m 700 "$KLIPPERAI_DATA_DIR"' in install
    nginx = (ROOT / "deployment/nginx/klipperai.conf").read_text()
    assert "access_log off;" in nginx and "proxy_set_header Host $http_host;" in nginx
    assert "client_max_body_size" not in nginx
