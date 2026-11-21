"""Isolated real HTTP process for installer and proxy integration checks."""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
import urllib.request
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def free_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


def http(base: str, path: str, body=None):
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(
        base + path, data=data, headers={"Content-Type": "application/json"}
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    return opener.open(request, timeout=3)


@contextmanager
def daemon(root: Path, extra: dict[str, str] | None = None):
    port = free_port()
    environment = {key: value for key, value in os.environ.items() if not key.startswith("KAI_")}
    environment.update(
        {
            "PYTHONPATH": str(ROOT),
            "PYTHONDONTWRITEBYTECODE": "1",
            "KAI_CONFIG_FILE": str(root / "missing.cfg"),
            "KAI_DATA_DIR": str(root / "app-data"),
            "KAI_PROVIDER_STORAGE_DIR": str(root / "private"),
            "KAI_PRINTER_DATA_ROOT": str(root / "printer"),
            "KAI_MAINSAIL_CONFIG_DIR": str(root / "printer/config"),
            "KAI_PROJECT_CHECKOUT_PATH": str(root / "no-checkout"),
            "KAI_HOST": "127.0.0.1",
            "KAI_PORT": str(port),
            "KAI_ROOT_PATH": "/kai",
            "KAI_MOONRAKER_URL": "http://127.0.0.1:1",
            "KAI_MOONRAKER_AGENT_ENABLED": "false",
            "KAI_COLLECT_HOST_LOGS": "false",
            "KAI_COLLECT_SYSTEMD_DIAGNOSTICS": "false",
        }
    )
    environment.update(extra or {})
    base = f"http://127.0.0.1:{environment['KAI_PORT']}"
    with (root / "boot.log").open("w") as log:
        process = subprocess.Popen(
            [sys.executable, "-m", "kai_agent"],
            cwd=root,
            env=environment,
            stdout=log,
            stderr=subprocess.STDOUT,
        )
        try:
            deadline = time.monotonic() + 20
            while True:
                try:
                    with http(base, "/readyz") as response:
                        assert json.load(response)["printer_access"] == "read_only"
                    break
                except OSError:
                    if process.poll() is not None or time.monotonic() >= deadline:
                        raise AssertionError((root / "boot.log").read_text()[-6000:])
                    time.sleep(0.1)
            yield base
        finally:
            if os.name == "nt" and process.poll() is None:
                subprocess.run(
                    ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                    check=False,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            else:
                process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
