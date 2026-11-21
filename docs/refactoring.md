# Layout migration and validation

The project now uses the requested flat Python package: `kai_agent/`.
Both flat and `src/` layouts are valid; installed-wheel testing protects this
choice against checkout-only import behavior. Fresh installations use the
`kai-agent` and `kai-detect-profile` commands, `KAI_*` environment variables and
the `/kai/` public URL. Internal Python imports use `kai_agent`; old branding
aliases are not installed.

| Previous module | New owners |
| --- | --- |
| `app.py` | `web/app.py`, `web/streaming.py` |
| `container.py` | `bootstrap/container.py` |
| `services.py` | `application/chat.py`, `application/request_context.py` |
| `sessions.py`, `intent.py` | `application/` |
| `settings.py`, `runtime_logging.py` | `runtime/` |
| `schemas.py`, `model_compat.py` | `domain/` (shared models), `contracts/` (HTTP and compatibility exports) |
| `moonraker.py`, `hostlogs.py`, `hostsystem.py` | `infrastructure/` |
| `diagnostics.py` | `diagnostics/models.py`, `collector.py`, `rules.py` |
| `printerconfig.py` | `config/models.py`, `collector.py`, `parser.py`, `targeting.py`, `lookup.py`, `macro_names.py`, `matching.py`, `vocabulary.py` |
| `printerprofile.py` | `profile/models.py`, `saved.py`, `persistence.py`, `collector.py`, `host.py`, `hardware.py`, `capabilities.py`, `addons.py` |
| `llm.py` | `providers/`, feature-owned `requests.py`, `config/templates/` |
| `workflows.py` | `workflows/` (single-pass LLM compatibility) and new `agent/` (iterative) |
| `detect_profile.py` | `cli/detect_profile.py` |

Design choices are intentionally small: dependency injection at the composition
root, protocols for provider/workflow ports, strategy objects for config proposals,
composed profile detectors, typed models and a tool registry. Pure transformations
remain functions; no framework or service locator was added.

Investigation storage is created under `data_dir`, outside printer config/G-code
directories. Domain models formerly imported through `contracts/api.py` remain
available there as compatibility exports. Agent tools now depend on narrow ports;
the loop itself exchanges typed investigation requests and results. The unused
approval/apply placeholder was removed because all printer edits are manual.

After pulling this change, reinstall the editable package or rerun the installer
so the old editable `src/` path is replaced:

```sh
python -m pip install -e '.[dev]'
python -m pytest
ruff check kai_agent tests tools
ruff format --check kai_agent tests tools
mypy kai_agent --ignore-missing-imports
python tools/project_map.py --check
uv build
node --test tests/*.test.mjs  # JS runtime checks, no npm dependencies
sh install.sh --check
```

The `uv` equivalent is `uv sync --extra dev`. On Windows, if a shared pytest temp
directory is inaccessible, use `-p no:cacheprovider --basetemp=.local/test-run-N`
with a fresh N (create `.local` first on a new checkout). Shell integration
tests require Bash and standard POSIX utilities. They also detect Git for
Windows when it is not on PATH; all host writes and service commands use fixtures.
See [frontend and installer ownership](frontend-and-installation.md).

Install the built wheel in a clean environment outside the repository and verify
`python -m kai_agent`, both profile CLI names, root/embed HTML and bundled
assets. Unit tests and wheel smoke tests do not validate a physical printer,
nginx deployment or live OpenAI model.
