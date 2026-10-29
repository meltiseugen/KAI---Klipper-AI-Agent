"""Short-lived native launcher: unwrap in RAM, then exec the application process."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from deployment.appliance_config import ApplianceConfig, environment_file


def launch(install: Path) -> None:
    import resource

    config = ApplianceConfig.load(install.resolve())
    os.umask(0o077)
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    environment = {**os.environ, **environment_file(config.environment)}
    environment["CREDENTIALS_DIRECTORY"] = str(config.credentials.deliver(config.runtime))
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    # Checkout is the source fallback; the selected wheel must precede it.
    current = config.install / ".klipperai-releases/current"
    environment["PYTHONPATH"] = str(current) + os.pathsep + str(config.install)
    # `python -m` puts cwd before PYTHONPATH; keep the selected release first there too.
    os.chdir(current.resolve() if current.is_symlink() else config.install)
    python = str(config.install / ".venv/bin/python")
    os.execve(python, [python, "-m", "klipperai_agent"], environment)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--install-dir", required=True, type=Path)
    args = parser.parse_args()
    if os.geteuid() != 0:
        parser.error("Native credentials must be delivered by root.")
    launch(args.install_dir)


if __name__ == "__main__":
    main()
