"""Portable shell fixtures; every host mutation is redirected into tmp_path."""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

import pytest


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
            conversion += f'if [ -n "${{{name}:-}}" ]; then export {name}="$(cygpath -w "${name}")"; fi\n'
    python.write_text(
        f'#!/bin/sh\n{conversion}exec "{Path(sys.executable).as_posix()}" "$@"\n',
        encoding="utf-8", newline="\n",
    )
    python.chmod(0o755)
    systemctl = fake_bin / "systemctl"
    systemctl.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8", newline="\n")
    systemctl.chmod(0o755)
    return {
        **os.environ,
        "PATH": os.pathsep.join((str(fake_bin), str(Path(shell).parent), os.environ["PATH"])),
        "KLIPPERAI_NO_SUDO": "1",
        "MSYS_ENV_CONV_EXCL": "KLIPPERAI_PREFIX",
        "KLIPPERAI_STATE_DIR": (tmp_path / "state").as_posix(),
    }
