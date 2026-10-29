# Release engineering

## Version and changelog

`klipperai_agent/domain/version.py` is the single version source for packaging,
HTTP metadata, the Moonraker extension and `klipperai-agent --version`. Use
`MAJOR.MINOR.PATCH`, optionally `aN`, `bN` or `rcN` for prereleases. Increment patch
for compatible fixes, minor for compatible features and major for breaking changes.
The current `0.1.0` is the development baseline, not evidence of a published release.

Prepare releases by reviewing `CHANGELOG.md`'s Unreleased section, setting the
version, updating `uv.lock`, and creating a dated changelog entry. Use
[the release notes template](releases/TEMPLATE.md). State settings, dependency and
database compatibility explicitly. Code rollback requires compatible stored data;
schema changes need a separate backup/migration/recovery plan.

## Checks and artifacts

The Linux workflow runs on pull requests, main/master pushes and `v*` tags. Python
3.10 and 3.13 run Ruff, mypy, the generated map check, the complete Python suite
with 100% statement coverage and the JavaScript module tests. It installs nginx so
the real `/klipperai/` test is required rather than silently skipped. CI keeps test
reports for 7 days and package artifacts for 14 days. Action references are pinned
to commits.

Linux CI also runs a separate root-owned native-process integration: real boot,
code selection, failed-start recovery and CLI rollback on a verified RAM filesystem.
This uses disposable printer/provider fixtures, not actual printer hardware.
Universal wheels include the operator `deployment` bootstrap package so native
startup and lifecycle fixes can travel with a code update.

```sh
uv sync --locked --extra dev
uv run --frozen ruff check klipperai_agent tests tools deployment integrations
uv run --frozen ruff format --check klipperai_agent tests tools deployment integrations
uv run --frozen mypy klipperai_agent integrations --ignore-missing-imports
uv run --frozen python tools/project_map.py --check
uv run --frozen python -m pytest
node --test tests/*.test.mjs
bash install.sh --check
bash -n uninstall.sh
uv build --out-dir dist
uv run --frozen python -m tools.release_artifacts dist
```

Use a clean output directory for each build. The artifact checker rejects private
data, unsafe archive paths, missing installer/UI files and mismatched wheel/source
versions, then writes `SHA256SUMS`. Tags must be exactly `v<version>`; CI checks that
against the built packages. Rebuild and verify artifacts after any source changes.

Install the wheel into a fresh virtual environment outside the checkout, then run
`python -m tools.smoke_installed --python /path/to/fresh-venv/bin/python`. The smoke
test starts an actual daemon process with temporary storage, checks readiness,
HTML/assets and session setup, and confirms Chat requires a provider. It does not
contact a printer or an LLM. On Windows, use the environment's `Scripts/python.exe`.

Publish only after review of passing checks and release notes. Attach the universal
wheel, complete source archive and checksums to an immutable version tag. CI builds
artifacts but does not publish a release or deploy to a printer. Record live printer
and provider acceptance separately from fixture and local package results.

For rapid printer fixes before a release, use [the SSH update workflow](printer-testing.md).

## Future one-line installer

Keep the existing interactive, reviewable `install.sh` as the installation engine.
A future small bootstrap should download a **version-pinned complete source
archive**, verify its published checksum (and signature when signing is available),
extract it safely into a private temporary directory, display the selected release
and invoke the included installer. It must preserve the full installer module
manifest, integration helpers and configuration examples; a lone downloaded
`install.sh` cannot work.

The current guided installer requires a Git checkout. The future bootstrap also
needs an explicit packaged-source installation mode (with manifest validation)
before archives can replace that checkout requirement. Archives are prepared and
validated here; a remote bootstrap is not implemented yet.

Do not point a one-line installer at mutable `main`, run an unverified network pipe
in a root shell, or silently upgrade dependencies/settings during a code update.
Separate initial installation from the SSH code-update path. A future bootstrap
must check Bash, supported Linux/systemd, Python, disk space and host architecture,
and fail clearly on unsupported vendor firmware. Release signing, hosting and that
bootstrap are future work; this milestone supplies validated archives and guidance.
