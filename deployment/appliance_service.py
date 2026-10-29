"""Native init service lifecycle. Controls only the recorded KlipperAI process."""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import time
from contextlib import contextmanager
from pathlib import Path

from deployment.appliance_config import ApplianceConfig
from deployment.appliance_credentials import private_directory, protect_process


def process_identity(pid: int, instance: str) -> str | None:
    if pid <= 1:
        return None
    try:
        root = Path("/proc") / str(pid)
        environment = (root / "environ").read_bytes().split(b"\0")
        if ("KLIPPERAI_NATIVE_INSTANCE=" + instance).encode() not in environment:
            return None
        # Field 22 follows the parenthesized comm field (which may contain spaces).
        return (root / "stat").read_text().rsplit(")", 1)[1].split()[19]
    except (OSError, IndexError):
        return None


class ApplianceService:
    def __init__(self, config: ApplianceConfig):
        self.config = config
        self.pidfile = config.runtime / "process.json"

    def configure(self, current: Path) -> None:
        if current != self.config.install / ".klipperai-releases/current":
            raise ValueError("Native release pointer does not match this installation.")
        self.config.credentials.master()

    @contextmanager
    def locked(self):
        private_directory(self.config.runtime)
        with (self.config.runtime / "service.lock").open("a") as lock:
            if os.name == "posix":
                import fcntl

                fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            yield

    def running(self) -> int | None:
        if self.pidfile.is_symlink():
            raise ValueError("Native process receipt must not be redirected.")
        try:
            data = json.loads(self.pidfile.read_text())
            pid = data["pid"]
            if (
                isinstance(pid, int)
                and pid > 1
                and isinstance(data["start"], str)
                and process_identity(pid, self.config.instance) == data["start"]
            ):
                return pid
        except (OSError, ValueError, KeyError):
            pass
        return None

    def start(self) -> None:
        with self.locked():
            self._start()

    def _start(self) -> None:
        if self.running():
            return
        self.config.credentials.deliver(self.config.runtime)
        private_directory(self.config.runtime)
        environment = {
            key: value
            for key, value in os.environ.items()
            if not key.startswith("KLIPPERAI_")
            and key not in {"PYTHONPATH", "CREDENTIALS_DIRECTORY"}
        }
        environment["KLIPPERAI_NATIVE_INSTANCE"] = self.config.instance
        release = self.config.install / ".klipperai-releases/current"
        working = release if release.is_symlink() else self.config.install
        process = subprocess.Popen(
            [
                str(self.config.install / ".venv/bin/python"),
                "-m",
                "deployment.appliance_runtime",
                "--install-dir",
                str(self.config.install),
            ],
            cwd=working,
            env=environment,
            start_new_session=True,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            deadline = time.monotonic() + 5
            while True:
                identity = process_identity(process.pid, self.config.instance)
                if identity:
                    self.pidfile.write_text(json.dumps({"pid": process.pid, "start": identity}))
                    self.pidfile.chmod(0o600)
                    return
                if process.poll() is not None or time.monotonic() >= deadline:
                    raise RuntimeError(
                        "Native KlipperAI launcher failed. Inspect the application runtime log."
                    )
                time.sleep(0.05)
        except BaseException:
            process.terminate()
            process.wait(timeout=5)
            raise

    def stop(self) -> None:
        with self.locked():
            self._stop()

    def _stop(self) -> None:
        pid = self.running()
        if pid:
            os.kill(pid, signal.SIGTERM)
            deadline = time.monotonic() + 15
            while self.running():
                if time.monotonic() >= deadline:
                    os.kill(pid, signal.SIGKILL)
                    break
                time.sleep(0.1)
        self.pidfile.unlink(missing_ok=True)
        (self.config.runtime / "klipperai-provider-master").unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("start", "stop", "restart", "status"))
    parser.add_argument("--install-dir", required=True, type=Path)
    args = parser.parse_args()
    if os.name != "posix" or os.geteuid() != 0:
        parser.error("The native appliance service is managed by root.")
    protect_process()
    config = ApplianceConfig.load(args.install_dir.resolve())
    service = ApplianceService(config)
    if args.action in {"stop", "restart"}:
        service.stop()
    if args.action in {"start", "restart"}:
        service.start()
    if args.action == "status":
        print("running" if service.running() else "stopped")
        raise SystemExit(0 if service.running() else 3)


if __name__ == "__main__":
    main()
