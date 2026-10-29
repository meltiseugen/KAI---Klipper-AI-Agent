"""Validated, non-secret native service installation receipt."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path

RECEIPT = ".klipperai-appliance.json"
INIT_SCRIPT = Path("/etc/init.d/S99klipperai")


@dataclass(frozen=True)
class ApplianceConfig:
    install: Path
    environment: Path
    host_key: Path
    wrapped_master: Path
    runtime: Path
    instance: str

    @property
    def credentials(self):
        from deployment.appliance_credentials import HostCredentials

        return HostCredentials(self.host_key, self.wrapped_master)

    def save(self) -> None:
        path = self.install / RECEIPT
        body = json.dumps({name: str(value) for name, value in vars(self).items()}) + "\n"
        if path.exists() or path.is_symlink():
            if self.load(self.install) != self:
                raise ValueError(
                    "Native service settings differ; preserve the original installation receipt."
                )
            return
        from deployment.appliance_credentials import create_private

        create_private(path, body.encode())

    @classmethod
    def load(cls, install: Path) -> ApplianceConfig:
        path = install / RECEIPT
        if path.is_symlink() or path.stat().st_nlink != 1:
            raise ValueError("Native service receipt must not be redirected.")
        if os.name != "nt" and (path.stat().st_uid != os.geteuid() or path.stat().st_mode & 0o022):
            raise ValueError(
                "Native service receipt must be root-owned and protected from other users."
            )
        with path.open() as handle:
            data = json.loads(handle.read(8193))
        config = cls(
            **{key: value if key == "instance" else Path(value) for key, value in data.items()}
        )
        if config.install != install.resolve() or not re.fullmatch(
            r"[a-f0-9]{32}", config.instance
        ):
            raise ValueError("Native service receipt identity is invalid.")
        for value in (
            config.install,
            config.environment,
            config.host_key,
            config.wrapped_master,
            config.runtime,
        ):
            if (
                not value.is_absolute()
                or (os.name != "nt" and not re.fullmatch(r"/[A-Za-z0-9_./-]+", value.as_posix()))
                or ".." in value.parts
            ):
                raise ValueError("Native paths must be plain absolute Linux paths.")
        return config


def environment_file(path: Path) -> dict[str, str]:
    # Parse generated metadata without sourcing shell code, expanding variables or echoing values.
    import shlex

    values = {}
    for line in path.read_text().splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        words = shlex.split(line)
        if len(words) != 1 or "=" not in words[0]:
            raise ValueError("Invalid appliance environment metadata.")
        name, value = words[0].split("=", 1)
        if not re.fullmatch(r"KLIPPERAI_[A-Z0-9_]+", name) or name.endswith("API_KEY"):
            raise ValueError(
                "Environment metadata must contain only non-secret application settings."
            )
        values[name] = value
    return values
