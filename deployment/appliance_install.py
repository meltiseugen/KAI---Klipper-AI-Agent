"""Native appliance bootstrap; operator-only and never exposed by HTTP or to models."""

from __future__ import annotations

import argparse
import os
import shlex
import sqlite3
import sys
from pathlib import Path

from deployment.appliance_config import INIT_SCRIPT, RECEIPT, ApplianceConfig
from deployment.appliance_credentials import (
    create_private,
    private_directory,
    protect_process,
    ram_backed,
)
from deployment.appliance_service import ApplianceService


def init_script(install: Path) -> str:
    return (
        "#!/bin/sh\n# Managed KlipperAI native service; no printer service control.\n"
        + "export PATH=/opt/bin:/opt/sbin:/usr/local/bin:/usr/bin:/usr/sbin:/bin:/sbin\n"
        + "BASE="
        + shlex.quote(str(install))
        + "\n"
        + 'if [ -L "$BASE/.klipperai-releases/current" ]; then\n'
        + '  cd "$BASE/.klipperai-releases/current" || exit 1\n'
        + 'else cd "$BASE" || exit 1; fi\n'
        + "exec "
        + shlex.quote(str(install / ".venv/bin/python"))
        + ' -m deployment.appliance_service "${1:-status}" --install-dir '
        + shlex.quote(str(install))
        + "\n"
    )


def provision(args: argparse.Namespace, raw_key: bytes) -> ApplianceConfig:
    from klipperai_agent.cli.credentials import initialize_credentials

    install = args.install_dir.resolve()
    if (install / RECEIPT).exists():
        config = ApplianceConfig.load(install)
        config.credentials.master()  # An installed host must never regenerate lost credentials.
        if (
            config.environment != args.environment_file
            or config.wrapped_master.parent != args.state_dir
        ):
            raise ValueError("Keep the existing native service credential and environment paths.")
    else:
        runtime = getattr(args, "runtime_dir", None) or next(
            (
                path
                for path in (Path("/run/klipperai"), Path("/tmp/klipperai-runtime"))
                if ram_backed(path)
            ),
            None,
        )
        if runtime is None or not ram_backed(runtime):
            raise ValueError("The native service requires a tmpfs or ramfs runtime location.")
        config = ApplianceConfig(
            install,
            args.environment_file,
            args.host_key_dir / "host.key",
            args.state_dir / "provider-master.enc",
            runtime,
            os.urandom(16).hex(),
        )
    for private in (config.host_key, config.wrapped_master):
        for protected in (install, args.printer_data_root, args.storage_dir.parent):
            if private.resolve().is_relative_to(protected.resolve()):
                raise ValueError(
                    "Host credential files must be separate from application data, checkout and printer files."
                )
    private_directory(args.state_dir)
    service = ApplianceService(config)
    service.stop()
    config.credentials.provision()
    config.save()
    original_directory = os.environ.get("CREDENTIALS_DIRECTORY")
    os.environ["CREDENTIALS_DIRECTORY"] = str(config.credentials.deliver(config.runtime))
    try:
        initialize_credentials(args, raw_key)
    finally:
        (config.runtime / "klipperai-provider-master").unlink(missing_ok=True)
        if original_directory is None:
            os.environ.pop("CREDENTIALS_DIRECTORY", None)
        else:
            os.environ["CREDENTIALS_DIRECTORY"] = original_directory
    text = init_script(install)
    if INIT_SCRIPT.exists():
        if INIT_SCRIPT.is_symlink() or INIT_SCRIPT.read_text() != text:
            raise ValueError(
                "Existing native init script differs; preserve it and resolve the checkout path."
            )
    else:
        create_private(INIT_SCRIPT, text.encode())
    INIT_SCRIPT.chmod(0o755)
    return config


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--install-dir", required=True, type=Path)
    parser.add_argument("--environment-file", required=True, type=Path)
    parser.add_argument("--state-dir", default=Path("/usr/data/klipperai-host"), type=Path)
    parser.add_argument("--host-key-dir", default=Path("/usr/data/.klipperai-host-key"), type=Path)
    parser.add_argument(
        "--runtime-dir", type=Path, help="Verified tmpfs/ramfs location; normally auto-detected."
    )
    parser.add_argument("--storage-dir", required=True, type=Path)
    parser.add_argument("--legacy-storage-dir", required=True, type=Path)
    parser.add_argument("--legacy-config-file", type=Path)
    parser.add_argument("--printer-data-root", required=True, type=Path)
    parser.add_argument("--provider", default="openai", choices=("openai",))
    parser.add_argument("--model", required=True)
    args = parser.parse_args()
    args.checkout_dir = args.install_dir
    if os.name != "posix" or os.geteuid() != 0:
        parser.error("Native appliance installation requires root.")
    protect_process()
    raw = sys.stdin.buffer.read(1025)
    if len(raw) > 1024:
        parser.error("Provider key input is too long.")
    try:
        provision(args, raw)
    except (OSError, ValueError, sqlite3.Error):
        print(
            "Native credential setup failed; check the original host key/master, private storage and input. No secret values are printed.",
            file=sys.stderr,
        )
        raise SystemExit(1) from None
    print("Native KlipperAI init service and encrypted credentials are ready.")


if __name__ == "__main__":
    main()
