"""Checksums, archive isolation and reproducible release identity."""

import hashlib
import io
import tarfile
import zipfile

import pytest

from deployment.artifacts import inspect_wheel
from klipperai_agent.domain.version import __version__
from tools import release_artifacts


def wheel_file(directory, *, extra=None, version=__version__):
    path = directory / f"klipperai-{version}-py3-none-any.whl"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("klipperai_agent/__init__.py", "")
        archive.writestr(
            f"klipperai-{version}.dist-info/METADATA", f"Name: klipperai\nVersion: {version}\n"
        )
        if extra:
            member, content = extra
            if isinstance(member, str):
                info = zipfile.ZipInfo(member)
                info.filename = member  # Keep malicious backslashes on Windows too.
                member = info
            archive.writestr(member, content)
    return path, hashlib.sha256(path.read_bytes()).hexdigest()


def source_file(directory, *, extra=None, version=__version__, omit=None):
    path = directory / f"klipperai-{version}.tar.gz"
    names = [
        "install.sh",
        "uninstall.sh",
        "deployment/installer/modules.txt",
        "deployment/update.py",
        "tools/deploy.py",
        "CHANGELOG.md",
        "docs/RELEASING.md",
        "klipperai_agent/web/templates/embed.html",
        "PKG-INFO",
    ]
    with tarfile.open(path, "w:gz") as archive:
        for name in names:
            if name == omit:
                continue
            body = (
                f"Name: klipperai\nVersion: {version}\n".encode()
                if name == "PKG-INFO"
                else b"example"
            )
            info = tarfile.TarInfo(f"klipperai-{version}/" + name)
            info.size = len(body)
            archive.addfile(info, io.BytesIO(body))
        if extra:
            info = tarfile.TarInfo(extra)
            archive.addfile(info, io.BytesIO(b""))
    return path


@pytest.mark.parametrize(
    "name",
    [
        "../outside",
        "/outside",
        "klipperai_agent/../../outside",
        "klipperai_agent\\bad.py",
        "outside.py",
        "klipperai_agent/.env",
        "klipperai_agent/history.sqlite3",
    ],
)
def test_wheel_rejects_paths_and_private_runtime_files(tmp_path, name):
    wheel, checksum = wheel_file(tmp_path, extra=(name, "private"))
    with pytest.raises(ValueError):
        inspect_wheel(wheel, checksum)


def test_wheel_checks_identity_hash_and_links(tmp_path):
    wheel, checksum = wheel_file(tmp_path)
    assert inspect_wheel(wheel, checksum)["build"] == checksum[:16]
    with pytest.raises(ValueError, match="checksum"):
        inspect_wheel(wheel, "a" * 64)
    link = zipfile.ZipInfo("klipperai_agent/link.py")
    link.external_attr = 0o120777 << 16
    wheel, checksum = wheel_file(tmp_path, extra=(link, "elsewhere"))
    with pytest.raises(ValueError, match="symlink"):
        inspect_wheel(wheel, checksum)


def test_release_matches_tag_and_writes_exact_checksums(tmp_path):
    wheel, _ = wheel_file(tmp_path)
    source = source_file(tmp_path)
    assert release_artifacts.check(tmp_path, "v" + release_artifacts.source_version()) == [
        wheel,
        source,
    ]
    for line, path in zip((tmp_path / "SHA256SUMS").read_text().splitlines(), (wheel, source)):
        assert line == hashlib.sha256(path.read_bytes()).hexdigest() + "  " + path.name
    with pytest.raises(ValueError, match="tag"):
        release_artifacts.check(tmp_path, "v99.0.0")


@pytest.mark.parametrize(
    "extra",
    [
        "release/.env",
        "release/.local/private",
        "release/.venv/file",
        "release/history.db",
        "release/../bad",
        "/outside",
    ],
)
def test_source_release_rejects_unsafe_or_private_content(tmp_path, extra):
    wheel_file(tmp_path)
    source_file(tmp_path, extra=extra)
    with pytest.raises(ValueError):
        release_artifacts.check(tmp_path)


def test_release_requires_complete_installation_and_matching_versions(tmp_path):
    with pytest.raises(ValueError, match="one wheel"):
        release_artifacts.check(tmp_path)
    wheel, _ = wheel_file(tmp_path, version="9.0.0")
    source = source_file(tmp_path)
    with pytest.raises(ValueError, match="disagree"):
        release_artifacts.check(tmp_path)
    wheel.unlink()
    wheel_file(tmp_path)
    source.unlink()
    source_file(tmp_path, omit="install.sh")
    with pytest.raises(ValueError, match="missing"):
        release_artifacts.check(tmp_path)
