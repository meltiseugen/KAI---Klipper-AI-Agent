from __future__ import annotations

import json
import socket
import subprocess
import threading
from pathlib import Path

def test_auto_reapply_runner_coordinates_pending_update(tmp_path: Path, shell, shell_env) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    patch_script = repo_root / "integrations/octoeverywhere/apply-local-klipperai-route-patch.sh"
    install_script = repo_root / "integrations/octoeverywhere/install-auto-reapply.sh"
    oe_root = tmp_path / "octoeverywhere"
    router = oe_root / "moonraker_octoeverywhere/moonrakerapirouter.py"
    ui = oe_root / "moonraker_octoeverywhere/static/oe-ui.js"
    router.parent.mkdir(parents=True)
    ui.parent.mkdir(parents=True)
    router.write_text(
        "from typing import Optional\n\n"
        "class MoonrakerApiRouter:\n"
        "    def __init__(self):\n"
        '        self.Logger.info("MoonrakerApiRouter using bound to moonraker at "+self.MoonrakerHostAndPortStr)\n\n'
        "    # !! Interface Function !!\n"
        "    def MapRelativePathToAbsolutePathIfNeeded(self, relativeUrl, protocol):\n"
        "            relativeUrlLower = relativeUrl.lower()\n"
        "            return None\n",
        encoding="utf-8",
    )
    ui.write_text("    oe_detect_oe_loaded_index_and_inject_helpers();\n", encoding="utf-8")
    legacy_backup = router.with_name(f"{router.name}.klippyai-backup-20260522")
    legacy_backup.write_text("legacy backup\n", encoding="utf-8")

    state = {"commits_behind": 2}

    server_socket = socket.socket()
    server_socket.bind(("127.0.0.1", 0))
    server_socket.listen()
    server_port = server_socket.getsockname()[1]

    def serve_requests() -> None:
        for _ in range(3):
            connection, _address = server_socket.accept()
            with connection:
                request = b""
                while b"\r\n\r\n" not in request:
                    chunk = connection.recv(4096)
                    if not chunk:
                        break
                    request += chunk
                payload = {
                    "result": {
                        "version_info": {
                            "octoeverywhere": {
                                "commits_behind_count": state["commits_behind"],
                            }
                        }
                    }
                }
                body = json.dumps(payload).encode()
                headers = (
                    b"HTTP/1.1 200 OK\r\n"
                    b"Content-Type: application/json\r\n"
                    + f"Content-Length: {len(body)}\r\n".encode()
                    + b"Connection: close\r\n\r\n"
                )
                connection.sendall(headers + body)
        server_socket.close()

    thread = threading.Thread(target=serve_requests, daemon=True)
    thread.start()

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_systemctl = fake_bin / "systemctl"
    fake_systemctl.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    fake_systemctl.chmod(0o755)
    runner = tmp_path / "klipperai-octoeverywhere-reapply"
    systemd_dir = tmp_path / "systemd"
    state_dir = tmp_path / "state"
    env = {
        **shell_env,
        "KLIPPERAI_NO_SUDO": "1",
        "KLIPPERAI_OE_RUNNER_PATH": runner.as_posix(),
        "KLIPPERAI_SYSTEMD_DIR": systemd_dir.as_posix(),
        "KLIPPERAI_STATE_DIR": state_dir.as_posix(),
    }

    try:
        subprocess.run(
            [shell, patch_script.as_posix(), "--oe-root", oe_root.as_posix()],
            check=True,
            env=env,
            capture_output=True,
            text=True,
        )
        subprocess.run(
            [
                shell,
                install_script.as_posix(),
                "--install-dir",
                repo_root.as_posix(),
                "--oe-root",
                oe_root.as_posix(),
                "--moonraker-url",
                f"http://127.0.0.1:{server_port}",
            ],
            check=True,
            env=env,
            capture_output=True,
            text=True,
        )

        assert "KlipperAI local route patch init start" not in router.read_text(encoding="utf-8")
        assert (state_dir / "octoeverywhere-reapply.suspended").exists()
        assert (systemd_dir / "klipperai-octoeverywhere-reapply.path").exists()
        assert not legacy_backup.exists()
        assert (state_dir / "octoeverywhere-backups/legacy" / legacy_backup.name).exists()

        state["commits_behind"] = 0
        runner_env = env.copy()
        runner_env.pop("HOME", None)
        runner_env.pop("KLIPPERAI_STATE_DIR", None)
        subprocess.run(
            [shell, runner.as_posix()],
            check=True,
            env=runner_env,
            capture_output=True,
            text=True,
        )

        assert "KlipperAI local route patch init start" in router.read_text(encoding="utf-8")
        assert not (state_dir / "octoeverywhere-reapply.suspended").exists()
    finally:
        server_socket.close()
        thread.join(timeout=2)
