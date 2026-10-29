"""Build the current workspace and deploy code to a printer over operator-controlled SSH."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import shlex
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

from deployment.artifacts import inspect_wheel

ROOT = Path(__file__).resolve().parents[1]


def run(command: list[str], **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(command, check=True, **kwargs)


def build_wheel(directory: Path) -> Path:
    uv = shutil.which("uv")
    command = (
        [uv, "build", "--wheel", "--out-dir", str(directory)]
        if uv
        else [
            sys.executable,
            "-m",
            "pip",
            "wheel",
            "--no-deps",
            "--wheel-dir",
            str(directory),
            str(ROOT),
        ]
    )
    run(command, cwd=ROOT)
    wheels = list(directory.glob("klipperai-*-py3-none-any.whl"))
    if len(wheels) != 1:
        raise ValueError("Build must produce exactly one universal KlipperAI wheel.")
    return wheels[0]


def deploy(
    host: str,
    install: str,
    url: str,
    *,
    wheel: Path | None = None,
    rollback: bool = False,
    dry_run: bool = False,
    non_interactive: bool = False,
) -> None:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.@-]*", host):
        raise ValueError(
            "Use an SSH config alias or user@hostname; configure ports/keys in SSH config."
        )
    if not re.fullmatch(r"/[A-Za-z0-9_./-]+", install) or ".." in Path(install).parts:
        raise ValueError("Use the printer's plain absolute KlipperAI checkout path.")
    endpoint = urlsplit(url)
    if (
        endpoint.scheme != "http"
        or endpoint.hostname not in {"127.0.0.1", "localhost", "::1"}
        or endpoint.username
        or endpoint.password
        or endpoint.path != "/readyz"
        or endpoint.query
        or endpoint.fragment
    ):
        raise ValueError("Use the printer's direct loopback http://127.0.0.1:PORT/readyz URL.")
    if rollback and wheel is not None:
        raise ValueError("Choose a wheel deployment or rollback.")
    with tempfile.TemporaryDirectory(prefix="klipperai-deploy-") as directory:
        if not rollback:
            wheel = wheel.resolve() if wheel else build_wheel(Path(directory))
            if wheel.stat().st_size > 32 * 1024 * 1024:
                raise ValueError("Wheel exceeds the transfer size limit.")
            digest = hashlib.sha256(wheel.read_bytes()).hexdigest()
            identity = inspect_wheel(wheel, digest)
            print(f"Deploying KlipperAI {identity['version']} build {identity['build']} to {host}")
        if dry_run:
            print(
                f"Target: {host}:{install}; readiness: {url}; action: {'rollback' if rollback else 'stage code, verify, activate'}"
            )
            return
        remote = run(
            ["ssh", host, "umask 077; mktemp -d /tmp/klipperai-deploy.XXXXXXXX"],
            capture_output=True,
            text=True,
        ).stdout.strip()
        if not re.fullmatch(r"/tmp/klipperai-deploy\.[A-Za-z0-9]+", remote):
            raise ValueError("SSH returned an unexpected temporary staging path.")
        try:
            run(["ssh", host, "mkdir -m 700 -- " + shlex.quote(remote + "/deployment")])
            files = [
                ROOT / "deployment" / name
                for name in (
                    "update.py",
                    "releases.py",
                    "artifacts.py",
                    "appliance_config.py",
                    "appliance_credentials.py",
                    "appliance_service.py",
                )
            ]
            bundle = io.BytesIO()
            with tarfile.open(fileobj=bundle, mode="w") as archive:
                members = [(path, "deployment/" + path.name) for path in files]
                if not rollback:
                    assert wheel is not None
                    members.append((wheel, wheel.name))
                for path, name in members:
                    content = path.read_bytes()
                    member = tarfile.TarInfo(name)
                    member.size, member.mode = len(content), 0o600
                    archive.addfile(member, io.BytesIO(content))
            # BusyBox tar can consume the SSH stream; no remote scp/SFTP server is needed.
            run(
                ["ssh", "-T", host, "umask 077; tar -xf - -C " + shlex.quote(remote)],
                input=bundle.getvalue(),
            )
            arguments = ["--install-dir", install, "--url", url]
            if rollback:
                arguments.append("--rollback")
            else:
                assert wheel is not None
                arguments += ["--wheel", remote + "/" + wheel.name, "--sha256", digest]
            if non_interactive:
                arguments.append("--non-interactive")
            command = f"cd {shlex.quote(remote)} && " + shlex.join(
                [install + "/.venv/bin/python", "-m", "deployment.update", *arguments]
            )
            run(["ssh", "-T" if non_interactive else "-t", host, command])
        finally:
            # Only the private, validated mktemp path is removed on the remote host.
            subprocess.run(["ssh", host, "rm -rf -- " + shlex.quote(remote)], check=False)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target", help="SSH host/alias, or a name in .local/deploy-targets.json")
    parser.add_argument("--install-dir")
    parser.add_argument("--url")
    parser.add_argument("--wheel", type=Path)
    parser.add_argument("--rollback", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--non-interactive", action="store_true")
    options = parser.parse_args()
    profiles = ROOT / ".local/deploy-targets.json"
    saved = json.loads(profiles.read_text()) if profiles.exists() else {}
    target = saved.get(options.target, {})
    install = options.install_dir or target.get("install_dir")
    if not install:
        parser.error("Provide --install-dir or create .local/deploy-targets.json from the example.")
    deploy(
        target.get("host", options.target),
        install,
        options.url or target.get("url", "http://127.0.0.1:8811/readyz"),
        wheel=options.wheel,
        rollback=options.rollback,
        dry_run=options.dry_run,
        non_interactive=options.non_interactive,
    )


if __name__ == "__main__":
    main()
