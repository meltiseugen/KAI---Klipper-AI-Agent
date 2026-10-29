"""Operator-only code updater. This module is never exposed as an agent tool."""

from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit

from deployment.releases import SERVICE, ReleaseUpdater, run


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--install-dir", required=True, type=Path)
    parser.add_argument("--url", default="http://127.0.0.1:8811/readyz")
    parser.add_argument("--wheel", type=Path)
    parser.add_argument("--sha256")
    parser.add_argument("--rollback", action="store_true")
    parser.add_argument("--non-interactive", action="store_true")
    options = parser.parse_args()
    target = urlsplit(options.url)
    if (
        target.scheme != "http"
        or target.hostname not in {"127.0.0.1", "::1", "localhost"}
        or target.username
        or target.password
        or target.path != "/readyz"
        or target.query
        or target.fragment
    ):
        parser.error("Use the direct loopback http://127.0.0.1:PORT/readyz URL.")
    if not options.rollback and (not options.wheel or not options.sha256):
        parser.error("Provide --wheel and --sha256, or --rollback.")
    if not sys.platform.startswith("linux"):
        parser.error("The printer updater requires Linux.")
    from deployment.appliance_config import RECEIPT, ApplianceConfig

    native = (options.install_dir / RECEIPT).exists()
    if (native and os.geteuid() != 0) or (not native and os.geteuid() == 0):
        parser.error(
            "Use root for an installed native appliance service, or the unprivileged systemd service account."
        )
    if options.install_dir.resolve().stat().st_uid != os.geteuid():
        parser.error("The SSH/service account must own the installation directory.")
    service = None
    if native:
        from deployment.appliance_credentials import protect_process
        from deployment.appliance_service import ApplianceService

        protect_process()

        service = ApplianceService(ApplianceConfig.load(options.install_dir.resolve()))
    else:
        import pwd

        user = subprocess.check_output(
            ["systemctl", "show", "--property=User", "--value", SERVICE], text=True
        ).strip()
        if user != pwd.getpwuid(os.geteuid()).pw_name:
            parser.error("Connect as the configured KlipperAI service user.")
        run(["sudo", *(["-n"] if options.non_interactive else []), "-v"])
    os.umask(0o077)

    def interrupted(signum, frame):
        raise KeyboardInterrupt("Deployment interrupted; restoring the previous code selection.")

    signal.signal(signal.SIGTERM, interrupted)
    signal.signal(signal.SIGHUP, interrupted)
    updater = ReleaseUpdater(
        options.install_dir,
        options.url,
        service=service,
        privileged=lambda command: run(
            ["sudo", *(["-n"] if options.non_interactive else []), "--", *command]
        ),
    )
    import fcntl

    with (updater.root / ".update.lock").open("a") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        if options.rollback:
            updater.rollback()
        else:
            candidate = updater.prepare(options.wheel, options.sha256)
            updater.activate(candidate)
    print(
        "KlipperAI code selection is ready. Printer settings, credentials and history were preserved."
    )


if __name__ == "__main__":
    main()
