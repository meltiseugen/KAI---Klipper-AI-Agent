"""Check release identity/contents and write SHA256SUMS without publishing anything."""

from __future__ import annotations

import argparse
import ast
import hashlib
import tarfile
from email.parser import Parser
from pathlib import Path, PurePosixPath

from deployment.artifacts import inspect_wheel

ROOT = Path(__file__).resolve().parents[1]


def source_version() -> str:
    tree = ast.parse((ROOT / "klipperai_agent/domain/version.py").read_text())
    return next(
        ast.literal_eval(node.value)
        for node in tree.body
        if isinstance(node, ast.Assign)
        and any(isinstance(name, ast.Name) and name.id == "__version__" for name in node.targets)
    )


def check(directory: Path, tag: str | None = None) -> list[Path]:
    version = source_version()
    if tag is not None and tag != "v" + version:
        raise ValueError("Release tag must exactly match v<package version>.")
    wheels, sources = list(directory.glob("*.whl")), list(directory.glob("*.tar.gz"))
    if len(wheels) != 1 or len(sources) != 1:
        raise ValueError("Expected one wheel and one source archive.")
    wheel, source = wheels[0], sources[0]
    digest = hashlib.sha256(wheel.read_bytes()).hexdigest()
    if inspect_wheel(wheel, digest)["version"] != version:
        raise ValueError("Wheel and source version disagree.")
    with tarfile.open(source) as archive:
        names = set()
        for member in archive.getmembers():
            path = PurePosixPath(member.name)
            if path.is_absolute() or ".." in path.parts or member.issym() or member.islnk():
                raise ValueError("Unsafe source-archive member.")
            name = "/".join(path.parts[1:])
            if (
                ".local" in path.parts
                or ".venv" in path.parts
                or path.name == ".env"
                or path.suffix in {".sqlite3", ".sqlite", ".db"}
            ):
                raise ValueError("Source archive contains private runtime/development data.")
            names.add(name)
        required = {
            "install.sh",
            "uninstall.sh",
            "deployment/installer/modules.txt",
            "deployment/update.py",
            "tools/deploy.py",
            "CHANGELOG.md",
            "docs/RELEASING.md",
            "klipperai_agent/web/templates/embed.html",
        }
        if not required <= names:
            raise ValueError("Source archive is missing installation/release files.")
        pkg_info = next(
            member
            for member in archive.getmembers()
            if PurePosixPath(member.name).name == "PKG-INFO"
            and len(PurePosixPath(member.name).parts) == 2
        )
        metadata = Parser().parsestr(archive.extractfile(pkg_info).read().decode())
        if metadata["Version"] != version:
            raise ValueError("Source distribution version disagrees.")
    files = [wheel, source]
    (directory / "SHA256SUMS").write_text(
        "".join(
            f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}\n" for path in files
        ),
        encoding="utf-8",
    )
    return files


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--tag")
    options = parser.parse_args()
    for path in check(options.directory, options.tag):
        print(f"Verified {path.name}")


if __name__ == "__main__":
    main()
