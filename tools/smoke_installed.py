"""Boot an installed daemon with isolated storage and no printer/provider access."""

from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path


def request(base: str, path: str, body: dict | None = None) -> tuple[int, bytes]:
    data = json.dumps(body).encode() if body is not None else None
    query = urllib.request.Request(
        base + path, data=data, headers={"Content-Type": "application/json"}
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(query, timeout=3) as response:
        return response.status, response.read(2 * 1024 * 1024)


def smoke(python: Path) -> None:
    checkout = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix="klipperai-installed-smoke-") as directory:
        root = Path(directory)
        environment = {
            key: value
            for key, value in os.environ.items()
            if not key.startswith("KLIPPERAI_")
            and key not in {"PYTHONPATH", "CREDENTIALS_DIRECTORY"}
        }
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
        environment.update(
            {
                "KLIPPERAI_CONFIG_FILE": str(root / "app.cfg"),
                "KLIPPERAI_DATA_DIR": str(root / "data"),
                "KLIPPERAI_PROVIDER_STORAGE_DIR": str(root / "private"),
                "KLIPPERAI_PROJECT_CHECKOUT_PATH": str(root / "no-checkout"),
                "KLIPPERAI_PRINTER_DATA_ROOT": str(root / "printer"),
                "KLIPPERAI_MAINSAIL_CONFIG_DIR": str(root / "mainsail"),
                "KLIPPERAI_HOST": "127.0.0.1",
                "KLIPPERAI_PORT": str(port),
                "KLIPPERAI_ROOT_PATH": "/klipperai",
                "KLIPPERAI_MOONRAKER_URL": "http://127.0.0.1:1",
                "KLIPPERAI_MOONRAKER_AGENT_ENABLED": "false",
                "KLIPPERAI_HOST_FLIGHT_RECORDER_ENABLED": "false",
                "KLIPPERAI_COLLECT_HOST_LOGS": "false",
                "KLIPPERAI_COLLECT_SYSTEMD_DIAGNOSTICS": "false",
            }
        )
        origin = subprocess.check_output(
            [str(python), "-c", "import klipperai_agent; print(klipperai_agent.__file__)"],
            cwd=root,
            env=environment,
            text=True,
        ).strip()
        if Path(origin).resolve().is_relative_to(checkout):
            raise ValueError("Smoke test imported the checkout instead of the installed wheel.")
        bootstrap = subprocess.check_output(
            [
                str(python),
                "-c",
                "import deployment.appliance_service as service; print(service.__file__)",
            ],
            cwd=root,
            env=environment,
            text=True,
        ).strip()
        if Path(bootstrap).resolve().is_relative_to(checkout):
            raise ValueError(
                "Native bootstrap imported the checkout instead of the installed wheel."
            )
        subprocess.run(
            [str(python), "-m", "deployment.appliance_service", "--help"],
            cwd=root,
            env=environment,
            check=True,
            stdout=subprocess.DEVNULL,
        )
        version = subprocess.check_output(
            [str(python), "-m", "klipperai_agent", "--version"],
            cwd=root,
            env=environment,
            text=True,
        ).strip()
        with (root / "service.log").open("w") as log:
            process = subprocess.Popen(
                [str(python), "-m", "klipperai_agent"],
                cwd=root,
                env=environment,
                stdout=log,
                stderr=subprocess.STDOUT,
            )
            base = f"http://127.0.0.1:{port}"
            try:
                deadline = time.monotonic() + 30
                while True:
                    try:
                        status, body = request(base, "/readyz")
                        ready = json.loads(body)
                        assert status == 200 and ready["version"] == version
                        assert ready["printer_access"] == "read_only"
                        break
                    except (OSError, ValueError):
                        if process.poll() is not None or time.monotonic() >= deadline:
                            raise RuntimeError("Installed service failed to become ready.")
                        time.sleep(0.2)
                status, page = request(base, "/")
                assert status == 200 and b'data-api-base="/klipperai/api"' in page
                assert request(base, "/assets/embed.css")[0] == 200
                session = json.loads(request(base, "/api/ui-sessions", {})[1])["session_id"]
                bootstrap = json.loads(request(base, "/api/bootstrap?session_id=" + session)[1])
                assert bootstrap["provider_configured"] is False
                try:
                    request(base, "/api/chat", {"session_id": session, "message": "Check printer"})
                    raise AssertionError("A provider-free chat must not run.")
                except urllib.error.HTTPError as error:
                    assert error.code == 503
                print(
                    f"Installed {version}: service boot, readiness, UI/assets, sessions and provider gating passed."
                )
                print(origin)
            finally:
                if os.name == "nt" and process.poll() is None:
                    # Windows venv launchers create a child interpreter.
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
                    process.wait()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--python", required=True, type=Path)
    smoke(parser.parse_args().python.resolve())


if __name__ == "__main__":
    main()
