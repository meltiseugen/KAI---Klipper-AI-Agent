"""Portable shell fixtures; every host mutation is redirected into tmp_path."""

from __future__ import annotations

import importlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def isolated_provider_storage(monkeypatch, tmp_path):
    monkeypatch.setenv("KLIPPERAI_PROVIDER_STORAGE_DIR", str(tmp_path / "provider-secrets"))
    credentials = tmp_path / "systemd-credentials"
    credentials.mkdir()
    master = credentials / "klipperai-provider-master"
    master.write_bytes(b"t" * 32)
    master.chmod(0o600)
    monkeypatch.setenv("CREDENTIALS_DIRECTORY", str(credentials))


@pytest.fixture
def mainsail_maintenance(monkeypatch, tmp_path):
    from types import SimpleNamespace

    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "integrations/mainsail"))
    cli = importlib.import_module("nav_cli")
    config = tmp_path / "printer-data/config"
    config.mkdir(parents=True)
    state = config.parent / ".klipperai-mainsail"
    return SimpleNamespace(
        cli=cli,
        config=config,
        state=state,
        files=cli.NavigationFile(config, state),
        navigation=importlib.import_module("navigation"),
        io=importlib.import_module("navigation_file"),
        hook=importlib.import_module("nav_hook"),
        args=["--config-dir", str(config)],
    )


@pytest.fixture
def oe_maintenance(monkeypatch, tmp_path, oe_checkout):
    monkeypatch.syspath_prepend(
        str(Path(__file__).resolve().parents[1] / "integrations/octoeverywhere")
    )
    from types import SimpleNamespace

    cli = importlib.import_module("maintenance")
    state = cli.MaintenanceState(tmp_path / "maintenance-state")
    files = cli.PatchFiles(oe_checkout[0], cli.RoutePatch(), state)
    return SimpleNamespace(
        cli=cli,
        state=state,
        files=files,
        runtime=importlib.import_module("host_lock"),
        deployment=importlib.import_module("patch_files"),
        updates=importlib.import_module("update_coordinator"),
    )


@pytest.fixture
def oe_checkout(tmp_path):
    root = tmp_path / "octoeverywhere"
    router = root / "moonraker_octoeverywhere/moonrakerapirouter.py"
    ui = root / "moonraker_octoeverywhere/static/oe-ui.js"
    ui.parent.mkdir(parents=True)
    router.write_text(
        "from typing import Optional\n\n"
        "class MoonrakerApiRouter:\n"
        "    def __init__(self):\n"
        '        self.Logger.info("MoonrakerApiRouter using bound to moonraker at "+self.MoonrakerHostAndPortStr)\n\n'
        "    # !! Interface Function !!\n"
        "    def MapRelativePathToAbsolutePathIfNeeded(self, relativeUrl, protocol):\n"
        "            relativeUrlLower = relativeUrl.lower()\n"
        "            return None\n\n"
        "# unrelated local router change\n",
        encoding="utf-8",
    )
    ui.write_text(
        "    oe_detect_oe_loaded_index_and_inject_helpers();\n    // unrelated UI change\n",
        encoding="utf-8",
    )
    return root, router, ui


@pytest.fixture
def run_shell(shell, shell_env):
    def run(*args, env=None, check=True):
        result = subprocess.run(
            [shell, *(str(arg) for arg in args)],
            env=env or shell_env,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if check:
            assert result.returncode == 0, result.stdout + result.stderr
        return result

    return run


@pytest.fixture
def shell() -> str:
    candidate = shutil.which("sh")
    if candidate:
        return candidate
    git_shell = Path("C:/Program Files/Git/usr/bin/sh.exe")
    if git_shell.exists():
        return str(git_shell)
    pytest.skip("requires a POSIX shell or Git for Windows")


@pytest.fixture
def shell_env(tmp_path, shell) -> dict[str, str]:
    fake_bin = tmp_path / "shell-bin"
    fake_bin.mkdir()
    python = fake_bin / "python3"
    conversion = ""
    if os.name == "nt":
        for name in ("OE_ROUTER_FILE", "OE_UI_FILE", "OE_ROUTER_OUTPUT_FILE", "OE_UI_OUTPUT_FILE"):
            conversion += (
                f'if [ -n "${{{name}:-}}" ]; then export {name}="$(cygpath -w "${name}")"; fi\n'
            )
    python.write_text(
        f'#!/bin/sh\n{conversion}exec "{Path(sys.executable).as_posix()}" "$@"\n',
        encoding="utf-8",
        newline="\n",
    )
    python.chmod(0o755)
    systemctl = fake_bin / "systemctl"
    systemctl.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8", newline="\n")
    systemctl.chmod(0o755)
    return {
        **os.environ,
        "PATH": os.pathsep.join((str(fake_bin), str(Path(shell).parent), os.environ["PATH"])),
        "KLIPPERAI_NO_SUDO": "1",
        "MSYS2_ENV_CONV_EXCL": "KLIPPERAI_PREFIX",
        "MSYS2_ARG_CONV_EXCL": "/klipperai;/assistant/",
        "KLIPPERAI_STATE_DIR": (tmp_path / "state").as_posix(),
    }
