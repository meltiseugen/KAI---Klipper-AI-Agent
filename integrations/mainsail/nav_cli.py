"""Administrative Mainsail navigation CLI, outside the read-only agent runtime."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from nav_hook import config_user, install_hook, remove_hook, render_units, start_hook
from navigation import NavigationEntry
from navigation_file import NavigationFile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from host_lock import MaintenanceBusy, locked  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Maintain the KlipperAI Mainsail sidebar link")
    parser.add_argument("--config-dir", type=Path)
    parser.add_argument("--state-dir", type=Path, default=os.getenv("KLIPPERAI_MAINSAIL_STATE_DIR"))
    parser.add_argument("--settings-file", type=Path)
    parser.add_argument("--href", default="/klipperai/")
    parser.add_argument("--title", default="KlipperAI")
    parser.add_argument("--target", default="_blank")
    parser.add_argument("--position", type=int, default=85)
    parser.add_argument("--icon", default="")
    parser.add_argument("--user", help="Systemd user; defaults to the config directory owner")
    parser.add_argument("--interval", default="5min")
    mode = parser.add_mutually_exclusive_group()
    for name in ("check", "remove", "reconcile", "validate", "install-hook", "remove-hook"):
        mode.add_argument("--" + name, action="store_true")
    args = parser.parse_args(argv)
    units = Path(os.getenv("KLIPPERAI_SYSTEMD_DIR", "/etc/systemd/system"))
    try:
        if args.remove_hook:
            remove_hook(units)
            return 0
        if args.settings_file:
            saved = json.loads(args.settings_file.read_text(encoding="utf-8"))
            args.config_dir, args.state_dir = Path(saved["config_dir"]), Path(saved["state_dir"])
            entry = NavigationEntry(**saved["entry"])
        else:
            entry = NavigationEntry(args.title, args.href, args.target, args.position, args.icon)
        if args.config_dir is None or not args.config_dir.is_dir():
            raise ValueError("--config-dir must name an existing printer config directory")
        config = args.config_dir.resolve()
        state = (args.state_dir or config.parent / ".klipperai-mainsail").resolve()
        files = NavigationFile(config, state)
        if args.validate:
            print("Mainsail navigation options are valid.")
            return 0
        if args.check:
            before, desired = files.prepare(entry)
            changed = before[0] != desired
            print("Navigation: repair needed" if changed else "Navigation: current")
            return int(changed)
        if args.install_hook:
            user = args.user or config_user(config)
            render_units(config, state, user, args.interval)  # Validate before writing.
        with locked(state / "maintenance.lock"):
            disabled = state / "disabled"
            if args.install_hook:
                install_hook(config, state, entry, units, user, args.interval)
                disabled.unlink(missing_ok=True)
            elif args.reconcile and disabled.exists():
                print("[KlipperAI Mainsail] Auto-reapply paused by navigation removal.")
                return 0
            else:
                if args.remove:
                    disabled.touch()  # A pending watcher must not undo an explicit removal.
                changed = files.update(entry, args.remove)
                if not args.remove:
                    disabled.unlink(missing_ok=True)
                print(
                    "[KlipperAI Mainsail] Navigation updated."
                    if changed
                    else "[KlipperAI Mainsail] Navigation already matches."
                )
        if args.install_hook:
            start_hook()
        return 0
    except MaintenanceBusy as exc:
        print(f"[KlipperAI Mainsail] {exc}")
        return 0 if args.reconcile else 1
    except (
        OSError,
        ValueError,
        TypeError,
        KeyError,
        AttributeError,
        RuntimeError,
        subprocess.SubprocessError,
    ) as exc:
        print(f"[KlipperAI Mainsail] Maintenance failed: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
