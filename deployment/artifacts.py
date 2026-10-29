"""Validate an operator-supplied KlipperAI wheel before staging any code."""

from __future__ import annotations

import hashlib
import re
import stat
import zipfile
from email.parser import Parser
from pathlib import Path, PurePosixPath


def inspect_wheel(path: Path, expected_sha256: str) -> dict[str, str]:
    if path.stat().st_size > 32 * 1024 * 1024:
        raise ValueError("Wheel file exceeds the transfer size limit.")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if not re.fullmatch(r"[a-f0-9]{64}", expected_sha256) or digest != expected_sha256:
        raise ValueError("Wheel checksum mismatch.")
    if not path.name.startswith("klipperai-") or not path.name.endswith("-py3-none-any.whl"):
        raise ValueError("Deploy a universal KlipperAI wheel built on the development machine.")
    with zipfile.ZipFile(path) as wheel:
        total = 0
        for member in wheel.infolist():
            name = PurePosixPath(member.filename)
            if (
                name.is_absolute()
                or ".." in name.parts
                or "\\" in member.orig_filename
                or "\x00" in member.orig_filename
                or not name.parts
            ):
                raise ValueError("Unsafe wheel member path.")
            if name.parts[0] not in {"klipperai_agent", "deployment"} and not re.fullmatch(
                r"klipperai-[A-Za-z0-9.+_-]+\.dist-info", name.parts[0]
            ):
                raise ValueError("Wheel contains files outside the application package.")
            if stat.S_ISLNK(member.external_attr >> 16):
                raise ValueError("Wheel symlinks are not permitted.")
            if name.name == ".env" or name.suffix in {".sqlite", ".sqlite3", ".db"}:
                raise ValueError("Wheel contains private runtime data.")
            total += member.file_size
        if total > 32 * 1024 * 1024:
            raise ValueError("Application wheel exceeds the staging size limit.")
        metadata_paths = [name for name in wheel.namelist() if name.endswith(".dist-info/METADATA")]
        if len(metadata_paths) != 1:
            raise ValueError("Wheel must have exactly one distribution metadata document.")
        metadata = Parser().parsestr(wheel.read(metadata_paths[0]).decode("utf-8"))
        if metadata["Name"] != "klipperai" or not re.fullmatch(
            r"[0-9]+\.[0-9]+\.[0-9]+(?:(?:a|b|rc)[0-9]+)?", metadata["Version"] or ""
        ):
            raise ValueError("Unexpected distribution name/version.")
    return {"version": metadata["Version"], "build": digest[:16], "sha256": digest}
