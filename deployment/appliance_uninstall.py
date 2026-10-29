"""Remove only the native KlipperAI service and explicitly selected host credentials."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from deployment.appliance_config import INIT_SCRIPT, RECEIPT, ApplianceConfig
from deployment.appliance_install import init_script
from deployment.appliance_service import ApplianceService


def remove(install: Path, purge: bool = False) -> None:
    config = ApplianceConfig.load(install.resolve())
    if INIT_SCRIPT.exists() and (
        INIT_SCRIPT.is_symlink() or INIT_SCRIPT.read_text() != init_script(config.install)
    ):
        raise ValueError(
            "Native init script was changed; preserve it and resolve removal manually."
        )
    ApplianceService(config).stop()
    INIT_SCRIPT.unlink(missing_ok=True)
    if purge:
        # Exact files only; never recursively remove a credential, runtime or data directory.
        config.wrapped_master.unlink(missing_ok=True)
        config.host_key.unlink(missing_ok=True)
        (config.install / RECEIPT).unlink()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--install-dir", required=True, type=Path)
    parser.add_argument("--purge-credentials", action="store_true")
    args = parser.parse_args()
    if os.name != "posix" or os.geteuid() != 0:
        parser.error("Native appliance removal requires root.")
    remove(args.install_dir, args.purge_credentials)


if __name__ == "__main__":
    main()
