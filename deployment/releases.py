"""Code-only staging and rollback. Never edits printer files, credentials or databases."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable, Protocol

from deployment.artifacts import inspect_wheel

SERVICE = "klipperai-agent.service"
DROPIN = Path("/etc/systemd/system/klipperai-agent.service.d/50-klipperai-release.conf")


class ServiceControl(Protocol):
    def configure(self, current: Path) -> None: ...
    def stop(self) -> None: ...
    def start(self) -> None: ...


def run(command: list[str], **kwargs) -> None:
    subprocess.run(command, check=True, **kwargs)


def admin(command: list[str]) -> None:
    run(["sudo", "--", *command])


def probe(url: str) -> dict:
    # Only a loopback endpoint is accepted by the CLI; never sends a credential.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(url, timeout=2) as response:
        return json.loads(response.read(4097))


class ReleaseUpdater:
    def __init__(
        self,
        install: Path,
        url: str,
        *,
        execute: Callable = run,
        privileged: Callable = admin,
        health: Callable = probe,
        service: ServiceControl | None = None,
    ):
        self.install = install.resolve()
        self.python = self.install / ".venv/bin/python"
        if not self.python.is_file() or not (self.install / "pyproject.toml").is_file():
            raise ValueError("Use the existing KlipperAI checkout with its installed .venv.")
        self.root = self.install / ".klipperai-releases"
        if self.root.is_symlink():
            raise ValueError("Release storage must not be a symlink.")
        self.root.mkdir(mode=0o700, exist_ok=True)
        self.current = self.root / "current"
        self.previous = self.root / "previous.json"
        if self.previous.is_symlink() or (
            self.previous.exists() and self.previous.stat().st_nlink != 1
        ):
            raise ValueError("Previous-release receipt must not be redirected.")
        self.url = url
        self.execute, self.privileged, self.health = execute, privileged, health
        self.service = service

    def selected(self) -> Path | None:
        if self.current.is_symlink():
            return self.checked_target(self.current.resolve())
        if self.current.exists():
            raise ValueError("Refusing to replace unmanaged release-current content.")
        return None

    def checked_target(self, target: Path) -> Path:
        if (
            target.parent != self.root
            or target.is_symlink()
            or not re.fullmatch(r"[a-f0-9]{16}", target.name)
            or not target.is_dir()
        ):
            raise ValueError("Release target must be an existing managed release directory.")
        with (target / "klipperai_agent/build-info.json").open() as handle:
            metadata = json.loads(handle.read(4097))
        if not isinstance(metadata, dict) or metadata.get("build") != target.name:
            raise ValueError("Release identity does not match its directory.")
        return target

    def point(self, target: Path | None) -> None:
        self.selected()  # Validate the existing pointer before replacing/removing it.
        if target is None:
            self.current.unlink(missing_ok=True)
            return
        self.checked_target(target)
        temporary = self.root / (".next-" + os.urandom(8).hex())
        try:
            temporary.symlink_to(target, target_is_directory=True)
            os.replace(temporary, self.current)
        finally:
            temporary.unlink(missing_ok=True)

    def prepare(self, wheel: Path, checksum: str) -> Path:
        metadata = inspect_wheel(wheel, checksum)
        target = self.root / metadata["build"]
        if target.exists():
            self.checked_target(target)
            self.verify(target)
            return target
        target.mkdir(mode=0o700)
        environment = {
            **os.environ,
            "PYTHONPATH": str(target),
            "PIP_DISABLE_PIP_VERSION_CHECK": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
        }
        try:
            self.execute(
                [
                    str(self.python),
                    "-m",
                    "pip",
                    "install",
                    "--no-index",
                    "--no-deps",
                    "--no-compile",
                    "--target",
                    str(target),
                    str(wheel.resolve()),
                ],
                env=environment,
                cwd=target,
            )
            package = target / "klipperai_agent"
            self.verify(target)
            # A complete marker is written only after successful preflight.
            (package / "build-info.json").write_text(json.dumps(metadata) + "\n")
            self.checked_target(target)
        except BaseException:
            # Only this newly created, validated child is removed; user data is elsewhere.
            if target.parent == self.root and not target.is_symlink():
                shutil.rmtree(target)
            raise
        return target

    def verify(self, target: Path) -> None:
        # Recheck reused releases too: shared dependencies may have changed.
        environment = {**os.environ, "PYTHONPATH": str(target), "PYTHONDONTWRITEBYTECODE": "1"}
        self.execute([str(self.python), "-m", "pip", "check"], env=environment, cwd=target)
        self.execute(
            [
                str(self.python),
                "-c",
                "from klipperai_agent.web.app import create_app; from klipperai_agent.runtime.release import release_info; print(release_info())",
            ],
            env=environment,
            cwd=target,
        )

    def wait_ready(self, expected: str | None, timeout: float = 45) -> None:
        deadline = time.monotonic() + timeout
        while True:
            try:
                data = self.health(self.url)
                if (
                    data.get("status") == "ok"
                    and data.get("printer_access") == "read_only"
                    and (expected is None or data.get("build") == expected)
                ):
                    return
            except urllib.error.HTTPError as exc:
                if expected == "source" and exc.code == 404:
                    # The original editable install can predate /readyz.
                    try:
                        if (
                            self.health(self.url.removesuffix("/readyz") + "/healthz").get("status")
                            == "ok"
                        ):
                            return
                    except (OSError, ValueError):
                        pass
            except (OSError, ValueError, urllib.error.URLError):
                pass
            if time.monotonic() >= deadline:
                raise RuntimeError("The expected read-only build did not become ready.")
            time.sleep(0.5)

    def dropin(self) -> None:
        if self.service is not None:
            self.service.configure(self.current)
            return
        # This fixed unit drop-in is public code-path configuration, never a key file.
        value = str(self.current)
        if not re.fullmatch(r"/[A-Za-z0-9_./-]+", value):
            raise ValueError("Install path must use plain absolute Linux path characters.")
        text = f'[Service]\nEnvironment="PYTHONPATH={value}"\n'
        if DROPIN.exists():
            if DROPIN.read_text() != text:
                raise ValueError(
                    "Managed systemd drop-in differs; preserve it and resolve the install path manually."
                )
            return
        with tempfile.NamedTemporaryFile("w", delete=False) as handle:
            handle.write(text)
            path = Path(handle.name)
        try:
            self.privileged(["install", "-d", "-m", "755", str(DROPIN.parent)])
            self.privileged(["install", "-m", "644", str(path), str(DROPIN)])
            self.privileged(["systemctl", "daemon-reload"])
        finally:
            path.unlink(missing_ok=True)

    def activate(self, target: Path | None) -> None:
        if target is not None:
            self.checked_target(target)
        old = self.selected()
        receipt = self.previous.read_bytes() if self.previous.exists() else None
        self.dropin()
        try:
            self.control("stop")
            self.receipt(json.dumps({"target": old.name if old else None}).encode() + b"\n")
            self.point(target)
            self.control("start")
            self.wait_ready(target.name if target else "source")
        except BaseException as failure:
            try:
                self.control("stop")
                self.point(old)
                self.receipt(receipt)
                self.control("start")
            except BaseException as rollback_failure:
                raise RuntimeError(
                    f"Activation and automatic recovery failed ({rollback_failure}). Inspect {SERVICE} and the current release pointer manually."
                ) from failure
            # Legacy checkouts may predate /readyz. Their process is restarted;
            # report the failure without claiming that legacy readiness passed.
            raise RuntimeError(
                "Activation failed; previous code selection was restored and KlipperAI restarted. Inspect its journal if it remains unavailable."
            ) from failure
        self.prune()

    def control(self, action: str) -> None:
        if self.service is None:
            self.privileged(["systemctl", action, SERVICE])
        elif action == "stop":
            self.service.stop()
        else:
            self.service.start()

    def receipt(self, content: bytes | None) -> None:
        if content is None:
            self.previous.unlink(missing_ok=True)
            return
        temporary = self.root / (".receipt-" + os.urandom(8).hex())
        try:
            with temporary.open("xb") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.previous)
        finally:
            temporary.unlink(missing_ok=True)

    def rollback(self) -> None:
        data = json.loads(self.previous.read_text())
        name = data["target"]
        if name is not None and (
            not isinstance(name, str) or not re.fullmatch(r"[a-f0-9]{16}", name)
        ):
            raise ValueError("Invalid previous-release receipt.")
        self.activate(self.root / name if name else None)

    def prune(self) -> None:
        retained = {self.selected()}
        previous = json.loads(self.previous.read_text())["target"]
        if previous:
            retained.add(self.checked_target(self.root / previous))
        for target in self.root.iterdir():
            if (
                target in retained
                or target.is_symlink()
                or not re.fullmatch(r"[a-f0-9]{16}", target.name)
            ):
                continue
            try:
                self.checked_target(target)
            except (ValueError, OSError):
                continue  # Unrecognized content is preserved for the operator.
            shutil.rmtree(target)
