"""Administrative CLI; never registered as a model tool or printer API endpoint."""

from __future__ import annotations

import argparse
import os
import re
import subprocess
from pathlib import Path

from maintenance_state import MaintenanceBusy, MaintenanceState
from patch_files import PatchFiles
from route_patch import RoutePatch
from update_coordinator import MoonrakerUpdates, OctoEverywhereService, UpdateCoordinator


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Maintain the local KlipperAI OctoEverywhere patch."
    )
    parser.add_argument("--oe-root", type=Path, default=Path.home() / "octoeverywhere")
    parser.add_argument(
        "--state-dir", type=Path, default=Path(os.getenv("KLIPPERAI_STATE_DIR", "/etc/klipperai"))
    )
    parser.add_argument("--klipperai-prefix", default="/klipperai")
    parser.add_argument("--klipperai-port", default="8811")
    parser.add_argument("--nav-target", default="_blank")
    parser.add_argument("--service", default="octoeverywhere")
    parser.add_argument("--restart-service", action="store_true")
    parser.add_argument("--moonraker-url", default="http://127.0.0.1:7125")
    parser.add_argument("--update-manager", default="octoeverywhere")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--restore-original", "--restore", action="store_true")
    mode.add_argument("--reconcile", action="store_true")
    mode.add_argument(
        "--check", action="store_true", help="Read-only content check; exit 1 if repair is needed"
    )
    mode.add_argument(
        "--validate", action="store_true", help="Validate installation options without writes"
    )
    args = parser.parse_args(argv)
    try:
        prefix = "/" + (args.klipperai_prefix or "klipperai").strip("/")
        patch = RoutePatch(prefix, args.klipperai_port, args.nav_target)
        if not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.@-]*", args.service):
            raise ValueError("Invalid OctoEverywhere service name")
        if not args.moonraker_url.startswith(("http://", "https://")):
            raise ValueError("Moonraker URL must use HTTP or HTTPS")
        if args.validate:
            print("OctoEverywhere maintenance options are valid.")
            return 0
        state = MaintenanceState(args.state_dir)
        files = PatchFiles(args.oe_root, patch, state)
        coordinator = UpdateCoordinator(
            files,
            MoonrakerUpdates(args.moonraker_url, args.update_manager),
            OctoEverywhereService(args.service),
        )
        if args.check:
            plan = files.plan()
            print(f"Patch: {plan.status}")
            return int(bool(plan.changes))
        with state.locked():
            if args.reconcile:
                coordinator.reconcile()
            else:
                if files.git_busy():
                    raise RuntimeError("Git operation in progress; checkout unchanged")
                files.commit(files.plan(args.restore_original))
                if args.restore_original:
                    state.mark("reapply.suspended")
                coordinator.finish(args.restore_original, args.restart_service)
                print(
                    "[KlipperAI OE] Patch removed."
                    if args.restore_original
                    else "[KlipperAI OE] Patch is current."
                )
                if state.has("restart-pending"):
                    print("[KlipperAI OE] Restart OctoEverywhere to load the changed files.")
        return 0
    except MaintenanceBusy as exc:
        print(f"[KlipperAI OE] {exc}")
        return 0 if args.reconcile else 1
    except (
        OSError,
        ValueError,
        KeyError,
        TypeError,
        AttributeError,
        RuntimeError,
        SyntaxError,
        subprocess.SubprocessError,
    ) as exc:
        print(f"[KlipperAI OE] Maintenance failed: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
