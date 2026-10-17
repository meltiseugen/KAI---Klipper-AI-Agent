"""Install/remove a bounded systemd watcher and boot/fallback timer for the sidebar."""

from __future__ import annotations

import json
import os
import re
import subprocess
from dataclasses import asdict
from pathlib import Path

from navigation import NavigationEntry
from navigation_file import atomic_write

NAME = "klipperai-mainsail-reapply"


def systemctl(*args: str) -> None:
    subprocess.run(["sh", "-c", 'exec systemctl "$@"', NAME, *args], check=True, timeout=60)


def unit_path(path: Path, quoted: bool = False) -> str:
    value = path.as_posix()
    if any(ord(c) < 32 or c in '%$\\"' for c in value) or value != value.strip():
        raise ValueError("Systemd paths contain unsupported whitespace or special characters")
    # ExecStart parses quoted arguments; PathChanged takes a literal path.
    return json.dumps(value, ensure_ascii=False) if quoted else value


def config_user(config: Path) -> str:
    import pwd

    return pwd.getpwuid(config.stat().st_uid).pw_name  # type: ignore[attr-defined]


def render_units(config: Path, state: Path, user: str, interval: str) -> dict[str, str]:
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.-]*[$]?", user):
        raise ValueError("Invalid systemd service user")
    if not re.fullmatch(r"[1-9][0-9]*(s|min|h)", interval):
        raise ValueError("Interval must be a positive number followed by s, min or h")
    helper = Path(__file__).resolve().with_name("run-nav.sh")
    return {
        "service": f"""[Unit]
Description=Maintain the KlipperAI Mainsail sidebar link
After=local-fs.target
StartLimitIntervalSec=60
StartLimitBurst=5

[Service]
Type=oneshot
User={user}
ExecStart=/bin/sh {unit_path(helper, True)} --settings-file {unit_path(state / "settings.json", True)} --reconcile
TimeoutStartSec=60
""",
        "timer": f"""[Unit]
Description=Check the KlipperAI Mainsail sidebar at boot and periodically

[Timer]
OnBootSec=30s
OnUnitInactiveSec={interval}
AccuracySec=5s
Unit={NAME}.service

[Install]
WantedBy=timers.target
""",
        "path": f"""[Unit]
Description=Watch Mainsail custom navigation for replacement

[Path]
PathChanged={unit_path(config / ".theme")}
PathChanged={unit_path(config / ".theme/navi.json")}
Unit={NAME}.service

[Install]
WantedBy=multi-user.target
""",
    }


def install_hook(
    config: Path, state: Path, entry: NavigationEntry, units: Path, user: str, interval: str
) -> None:
    contents = render_units(config, state, user, interval)
    owner = config.stat()
    settings = dict(config_dir=str(config), state_dir=str(state), entry=asdict(entry))
    if hasattr(os, "chown"):
        os.chown(state, owner.st_uid, owner.st_gid)
        os.chown(state / "maintenance.lock", owner.st_uid, owner.st_gid)
    atomic_write(state / "settings.json", json.dumps(settings).encode(), owner)
    units.mkdir(parents=True, exist_ok=True)
    for suffix, text in contents.items():
        atomic_write(units / f"{NAME}.{suffix}", text.encode(), units.stat())
    systemctl("daemon-reload")
    systemctl("enable", "--now", f"{NAME}.timer", f"{NAME}.path")
    systemctl("restart", f"{NAME}.timer", f"{NAME}.path")
    # A missing/malformed nav file at installation must not disable future retries.
    # The caller releases the file lock before starting this service.


def start_hook() -> None:
    try:
        systemctl("start", f"{NAME}.service")
    except subprocess.SubprocessError as exc:
        print(
            f"[KlipperAI Mainsail] Initial check failed; startup/timer retries remain enabled: {exc}"
        )


def remove_hook(units: Path) -> None:
    systemctl("disable", "--now", f"{NAME}.timer", f"{NAME}.path")
    systemctl("stop", f"{NAME}.service")
    for suffix in ("timer", "path", "service"):
        (units / f"{NAME}.{suffix}").unlink(missing_ok=True)
    systemctl("daemon-reload")
