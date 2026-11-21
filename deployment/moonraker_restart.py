"""Read-only installer checks before/after an operator-owned Moonraker restart."""

from __future__ import annotations

import argparse
import json
import time
import urllib.request


def read_json(url: str) -> dict:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(url, timeout=3) as response:
        raw = response.read(65537)
    if len(raw) > 65536:
        raise ValueError("Moonraker status is too large.")
    result = json.loads(raw)
    if not isinstance(result, dict):
        raise ValueError("Invalid Moonraker status.")
    return result


def idle_status(payload: dict) -> bool:
    status = payload.get("result", {}).get("status", {})
    return (
        status.get("webhooks", {}).get("state") == "ready"
        and status.get("print_stats", {}).get("state") in {"standby", "complete", "cancelled"}
        and status.get("idle_timeout", {}).get("state") in {"Idle", "Ready"}
    )


def check_idle(url: str) -> bool:
    try:
        return idle_status(
            read_json(url.rstrip("/") + "/printer/objects/query?print_stats&webhooks&idle_timeout")
        )
    except (OSError, ValueError, AttributeError, TypeError):
        return False


def wait_ready(url: str, timeout: float = 30) -> bool:
    deadline = time.monotonic() + timeout
    while True:
        try:
            result = read_json(url.rstrip("/") + "/server/info").get("result", {})
            if result.get("klippy_connected") is True and result.get("klippy_state") == "ready":
                return True
        except (OSError, ValueError, AttributeError, TypeError):
            pass
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.5)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check-idle", action="store_true")
    mode.add_argument("--wait-ready", action="store_true")
    args = parser.parse_args()
    raise SystemExit(
        0 if (check_idle(args.url) if args.check_idle else wait_ready(args.url)) else 1
    )


if __name__ == "__main__":
    main()
