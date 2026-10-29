"""Pinned Entware bootstrap against fake binaries and a disposable /opt tree."""

import hashlib
import os

import pytest

from tests.test_installer import ROOT, bash


@pytest.mark.parametrize("valid", [True, False])
def test_download_is_unusable_until_its_pinned_checksum_matches(tmp_path, run_shell, valid):
    target = tmp_path / "download"
    expected = hashlib.sha256(b"fixture-download").hexdigest() if valid else "0" * 64
    bash(
        run_shell,
        """
set -euo pipefail
source "$1/deployment/installer/bootstrap.sh"
source "$1/deployment/installer/entware.sh"
TARGET="$2"
bootstrap_command_path() { [[ "$1" == curl ]]; }
curl() { printf fixture-download > "$TARGET"; }
if entware_download https://example.invalid/pinned "$TARGET" "$3"; then
  [[ "$4" == yes ]]
else
  [[ "$4" == no ]]
fi
""",
        ROOT.as_posix(),
        target.as_posix(),
        expected,
        "yes" if valid else "no",
    )


def isolated_entware(tmp_path):
    opt = tmp_path / "opt"
    persistent = tmp_path / "usr-data/opt"
    etc = tmp_path / "etc"
    (etc / "init.d").mkdir(parents=True)
    (tmp_path / "tmp").mkdir()
    elf = tmp_path / "shell-elf"
    elf.write_bytes(b"\x7fELF\x01\x01")
    source = (ROOT / "deployment/installer/entware.sh").read_text()
    for old, marker in (
        ("/opt/etc", "@OPTETC@"),
        ("/usr/data/opt", "@STORE@"),
        ("/opt", "@OPT@"),
        ("/etc", "@ETC@"),
        ("/bin/sh", "@ELF@"),
        ("/tmp/klipperai-entware", "@TEMP@"),
    ):
        source = source.replace(old, marker)
    for marker, path in (
        ("@OPTETC@", opt / "etc"),
        ("@STORE@", persistent),
        ("@OPT@", opt),
        ("@ETC@", etc),
        ("@ELF@", elf),
        ("@TEMP@", tmp_path / "tmp/klipperai-entware"),
    ):
        source = source.replace(marker, path.as_posix())
    # The generated POSIX executables still need the host shell, not the ELF probe fixture.
    source = source.replace("#!" + elf.as_posix(), "#!/bin/sh")
    module = tmp_path / "entware.sh"
    module.write_text(source, newline="\n")
    return module, opt, persistent, etc


def test_existing_opt_content_is_preserved_before_downloading_anything(tmp_path, run_shell):
    module, opt, persistent, etc = isolated_entware(tmp_path)
    opt.mkdir()
    keep = opt / "existing-user-settings"
    keep.write_text("preserve exactly")
    result = bash(
        run_shell,
        """
source "$1/deployment/installer/bootstrap.sh"
source "$2"
id() { echo 0; }
uname() { echo mips; }
entware_download() { echo unexpected-download; exit 99; }
if bootstrap_entware; then exit 99; fi
""",
        ROOT.as_posix(),
        module.as_posix(),
    )
    assert "preserved" in result.stderr
    assert "unexpected-download" not in result.stdout
    assert keep.read_text() == "preserve exactly"
    assert not persistent.exists() and not (etc / "init.d/S49klipperai-entware").exists()


def test_fresh_bootstrap_verifies_packages_over_tls_and_only_creates_owned_paths(
    tmp_path, run_shell
):
    module, opt, persistent, etc = isolated_entware(tmp_path)
    calls = tmp_path / "calls"
    curl = tmp_path / "fixture-curl"
    curl.write_text(
        """#!/bin/sh
if [ "$1" = --version ]; then exit 0; fi
printf 'curl:%s\\n' "$*" >> "$CALLS"
while [ "$#" -gt 0 ]; do
  if [ "$1" = -o ]; then printf trusted-package-data > "$2"; shift 2; else shift; fi
done
""",
        newline="\n",
    )
    curl.chmod(0o755)
    opkg = tmp_path / "fixture-opkg"
    opkg.write_text(
        """#!/bin/sh
printf 'opkg:%s\\n' "$*" >> "$CALLS"
if [ "$1" = update ]; then wget -q -O "$OPT/tmp/package-index" https://bin.entware.net/fixture/Packages.gz; fi
""",
        newline="\n",
    )
    opkg.chmod(0o755)
    emulate_links = ""
    if os.name == "nt":
        # Default Windows accounts cannot create symlinks; Linux exercises actual links.
        emulate_links = 'ln() { printf "link:%s\\n" "$*" >> "$CALLS"; mkdir -p "$3"; }'
    result = bash(
        run_shell,
        """
set -euo pipefail
source "$1/deployment/installer/bootstrap.sh"
source "$2"
export CALLS="$3" OPT="$4"
CURL="$5"
OPKG="$6"
id() { echo 0; }
uname() { echo mips; }
bootstrap_command_path() { if [[ "$1" == curl ]]; then printf '%s' "$CURL"; else command -v "$1"; fi; }
entware_download() {
  case "$1" in */opkg) cp "$OPKG" "$2";; *) printf pinned-ca > "$2";; esac
}
mktemp() {
  local path
  path="$(command mktemp "$@")"
  if command -v cygpath >/dev/null; then cygpath -u "$path"; else printf '%s' "$path"; fi
}
eval "$7"
bootstrap_entware
""",
        ROOT.as_posix(),
        module.as_posix(),
        calls.as_posix(),
        opt.as_posix(),
        curl.as_posix(),
        opkg.as_posix(),
        emulate_links,
    )
    assert result.returncode == 0
    assert "https://bin.entware.net/mipselsf-k3.4" in (opt / "etc/opkg.conf").read_text()
    text = calls.read_text()
    assert "opkg:update" in text
    assert "opkg:install entware-opt wget-ssl ca-bundle ca-certificates" in text
    assert "--cacert" in text and "--insecure" not in text and "--no-check-certificate" not in text
    assert (etc / "init.d/S49klipperai-entware").exists()
    assert persistent.is_dir()
