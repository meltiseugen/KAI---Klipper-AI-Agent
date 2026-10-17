from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def bash(run_shell, script, *args):
    return run_shell("-c", 'exec bash "$@"', "test", "-c", script, "test", *args)


def test_installer_entrypoint_and_side_effect_free_modules(run_shell):
    entrypoint = (ROOT / "install.sh").as_posix()
    assert "Usage:" in run_shell(entrypoint, "--help").stdout
    assert "syntax is valid" in run_shell(entrypoint, "--check").stdout
    assert run_shell(entrypoint, "--unknown", check=False).returncode == 2
    result = bash(
        run_shell,
        """
set -euo pipefail
while IFS= read -r module; do source "$1/deployment/installer/$module.sh"; done < "$1/deployment/installer/modules.txt"
for phase in preflight configure_paths configure_options install_python_package install_service_configuration install_access_integrations print_next_steps; do
  declare -F "$phase" >/dev/null
done
""",
        ROOT.as_posix(),
    )
    assert result.stdout == ""


def test_nginx_snippet_preserves_prefix_queries_and_streaming(tmp_path, run_shell):
    target = tmp_path / "nginx.conf"
    bash(
        run_shell,
        """
set -euo pipefail
source "$1/deployment/installer/nginx.sh"
OUTPUT="$2"
KLIPPERAI_ROOT_PATH=/assistant/printer
KLIPPERAI_PORT=8899
backup_file() { :; }
run_root() { [[ "$1" == install ]] || return 1; cp "${@: -2:1}" "$OUTPUT"; }
write_nginx_snippet
""",
        ROOT.as_posix(),
        target.as_posix(),
    )
    text = target.read_text()
    assert "location = /assistant/printer" in text
    assert "return 308 /assistant/printer/$is_args$args;" in text
    assert "location /assistant/printer/" in text
    assert "proxy_pass http://127.0.0.1:8899/;" in text
    assert "proxy_buffering off;" in text
    assert "proxy_read_timeout 300s;" in text
    assert "proxy_set_header Host $http_host;" in text
    assert 'proxy_set_header X-Forwarded-Host "";' in text
    assert 'proxy_set_header Forwarded "";' in text
    assert "access_log off;" in text
    assert "client_max_body_size" not in text


@pytest.mark.parametrize("valid", [True, False])
def test_nginx_reload_obeys_validation_even_inside_conditional(tmp_path, run_shell, valid):
    calls = tmp_path / "calls"
    bash(
        run_shell,
        """
set -euo pipefail
source "$1/deployment/installer/nginx.sh"
CALLS="$2"
VALID="$3"
pidof() { return 1; }
nginx() { :; }
run_root() {
  printf '%s\n' "$*" >> "$CALLS"
  if [[ "$*" == 'nginx -t' ]]; then [[ "$VALID" == yes ]]; return; fi
  if [[ "$*" == 'nginx -s reload' ]]; then return 1; fi
}
if reload_nginx; then [[ "$VALID" == yes ]]; else [[ "$VALID" == no ]]; fi
""",
        ROOT.as_posix(),
        calls.as_posix(),
        "yes" if valid else "no",
    )
    assert calls.read_text().splitlines() == (
        ["nginx -t", "nginx -s reload", "systemctl reload nginx"] if valid else ["nginx -t"]
    )


def test_mainsail_navigation_is_idempotent_and_preserves_printer_files(tmp_path, run_shell):
    config = tmp_path / "config"
    theme = config / ".theme"
    theme.mkdir(parents=True)
    printer = config / "printer.cfg"
    printer.write_bytes(b"[printer]\nkinematics: corexy\n")
    original = printer.read_bytes()
    nav = theme / "navi.json"
    existing = {"title": "Other", "href": "/other", "position": 1}
    nav.write_text(json.dumps([existing]))
    script = (ROOT / "integrations/mainsail/install-custom-nav.sh").as_posix()
    for _ in range(2):
        run_shell(
            "-c",
            'exec bash "$@"',
            "test",
            script,
            "--config-dir",
            config.as_posix(),
            "--href",
            "/assistant/printer/",
        )
    assert json.loads(nav.read_text()) == [
        existing,
        {
            "title": "KlipperAI",
            "href": "/assistant/printer/",
            "target": "_blank",
            "position": 85,
        },
    ]
    assert printer.read_bytes() == original


def test_guided_install_connects_navigation_to_auto_reapply(tmp_path, run_shell):
    result = bash(
        run_shell,
        """
set -euo pipefail
source "$1/deployment/installer/install-access-integrations.sh"
INSTALL_MAINSAIL_NAV=yes
INSTALL_MAINSAIL_AUTO_REAPPLY=yes
INSTALL_OCTOEVERYWHERE_PATCH=no
INSTALL_OCTOEVERYWHERE_AUTO_REAPPLY=no
SERVICE_NAME=klipperai-agent
log() { :; }
run_root() { :; }
install_mainsail_custom_nav() { echo nav; }
install_mainsail_auto_reapply() { echo hook; }
install_access_integrations
""",
        ROOT.as_posix(),
    )
    assert result.stdout.splitlines() == ["nav", "hook"]


def test_full_uninstall_stops_navigation_repair_before_removing_units(tmp_path, run_shell):
    units = tmp_path / "units"
    units.mkdir()
    for suffix in ("path", "timer", "service"):
        (units / f"klipperai-mainsail-reapply.{suffix}").touch()
    result = bash(
        run_shell,
        """
set -euo pipefail
export KLIPPERAI_SYSTEMD_DIR="$2"
source "$1/uninstall.sh"
run_root() {
  if [[ "$1" == systemctl ]]; then printf '%s\\n' "$*"; else "$@"; fi
}
remove_mainsail_auto_reapply
""",
        ROOT.as_posix(),
        units.as_posix(),
    )
    assert not list(units.iterdir())
    lines = result.stdout.splitlines()
    assert (
        "disable --now klipperai-mainsail-reapply.timer klipperai-mainsail-reapply.path" in lines[0]
    )
    assert lines[1] == "systemctl stop klipperai-mainsail-reapply.service"
    assert lines[-1] == "systemctl daemon-reload"
