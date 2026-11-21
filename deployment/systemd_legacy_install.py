"""Install an isolated root-owned credential helper; no printer or OS package changes."""

from __future__ import annotations

import argparse
import os
import re
import stat
import subprocess
import sys
from pathlib import Path

import Cryptodome

from deployment import appliance_credentials, systemd_legacy
from deployment.appliance_credentials import create_private, private_directory


def trusted_path(path: Path) -> None:
    """Persistent root services must never execute code writable by the agent UID."""
    for candidate in (path, *path.parents):
        info = candidate.lstat()
        if candidate.is_symlink() or (
            os.name != "nt" and (info.st_uid != 0 or info.st_mode & 0o022)
        ):
            raise ValueError("Root credential helper paths must be root-owned and not redirected.")


def units(python: Path, library: Path) -> dict[str, str]:
    for path in (python, library):
        if not re.fullmatch(r"/[A-Za-z0-9_./-]+", path.as_posix()):
            raise ValueError("Credential helper paths must be plain absolute Linux paths.")
    return {
        systemd_legacy.SOCKET_UNIT: (
            "[Unit]\nDescription=KAI private credential socket\n\n"
            "[Socket]\nListenStream=" + systemd_legacy.SOCKET + "\n"
            "SocketMode=0600\nSocketUser=root\nSocketGroup=root\n"
            "Accept=yes\nRemoveOnStop=yes\n"
        ),
        systemd_legacy.SERVICE_UNIT: (
            "[Unit]\nDescription=KAI private credential delivery\n\n"
            "[Service]\nType=exec\nUser=root\nGroup=root\n"
            f"ExecStart={python.as_posix()} -I {library.as_posix()}/runner.py serve\n"
            "StandardInput=socket\nStandardOutput=socket\nStandardError=journal\n"
            "UMask=0077\nLimitCORE=0\nNoNewPrivileges=yes\n"
            "ProtectSystem=strict\nProtectHome=yes\nPrivateTmp=yes\n"
            "PrivateDevices=yes\nRestrictAddressFamilies=AF_UNIX\n"
            "TimeoutStartSec=15\n"
        ),
    }


def copy_tree(source: Path, target: Path) -> None:
    if source.is_symlink() or not source.is_dir():
        raise ValueError("Cryptographic helper sources must be real directories.")
    if target.exists():
        trusted_path(target)
        if not target.is_dir():
            raise ValueError("Credential helper package is not a directory.")
    else:
        target.mkdir(mode=0o700)
    for child in source.iterdir():
        if child.name == "__pycache__":
            continue
        destination = target / child.name
        if child.is_symlink():
            raise ValueError("Redirected cryptographic helper sources are refused.")
        if child.is_dir():
            copy_tree(child, destination)
        else:
            copy_file(child, destination)


def copy_file(source: Path, target: Path) -> None:
    if not stat.S_ISREG(source.lstat().st_mode):
        raise ValueError("Credential helper source must be a regular file.")
    if target.exists() or target.is_symlink():
        trusted_path(target)
        if not target.is_file() or target.stat().st_nlink != 1:
            raise ValueError("Credential helper target must be a singly linked regular file.")
        target.write_bytes(source.read_bytes())
    else:
        create_private(target, source.read_bytes())


def install(library: Path = systemd_legacy.LIBRARY, unit_dir: Path = Path("/etc/systemd/system")):
    python = Path(sys._base_executable).resolve()
    trusted_path(python)
    trusted_path(library.parent)
    private_directory(library)
    trusted_path(library)
    # This snapshot is never imported from the user-owned checkout/venv at service startup.
    package = library / "deployment"
    private_directory(package)
    init = package / "__init__.py"
    if not init.exists():
        create_private(init, b"")
    trusted_path(init)
    for module in (appliance_credentials, systemd_legacy):
        copy_file(Path(module.__file__), package / Path(module.__file__).name)
    copy_tree(Path(Cryptodome.__file__).parent, library / "Cryptodome")
    runner = library / "runner.py"
    text = (
        "import sys\n"
        f"sys.path.insert(0, {str(library)!r})\n"
        "from deployment.systemd_legacy import main\nmain()\n"
    )
    if runner.exists() or runner.is_symlink():
        trusted_path(runner)
        if not runner.is_file() or runner.stat().st_nlink != 1:
            raise ValueError("Credential runner must be a private regular file.")
        runner.write_text(text)
    else:
        create_private(runner, text.encode())
    # Provision using the isolated, root-owned copy too. Never regenerate an existing master.
    modern = systemd_legacy.WRAPPED_MASTER.parent / "provider-master.cred"
    if modern.exists() or modern.is_symlink():
        raise ValueError(
            "Preserve the existing systemd encrypted master; backend conversion required."
        )
    subprocess.run([str(python), "-I", str(runner), "provision"], check=True)
    trusted_path(unit_dir)
    for name, content in units(python, library).items():
        path = unit_dir / name
        if path.exists() or path.is_symlink():
            trusted_path(path)
            if not path.is_file() or path.stat().st_nlink != 1:
                raise ValueError("Credential unit must be a regular file.")
            path.write_text(content)
        else:
            create_private(path, content.encode())
        path.chmod(0o644)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    if os.name != "posix" or os.geteuid() != 0:
        parser.error("Credential helper installation requires root.")
    try:
        install()
    except (OSError, ValueError, subprocess.SubprocessError):
        print("Private credential helper setup failed; original credentials kept.", file=sys.stderr)
        raise SystemExit(1) from None
    print("Root-owned systemd 247 credential helper is ready.")


if __name__ == "__main__":
    main()
