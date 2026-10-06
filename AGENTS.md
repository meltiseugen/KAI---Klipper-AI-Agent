# Working in KlipperAI

Start with [docs/PROJECT_MAP.md](docs/PROJECT_MAP.md). It maps user-visible changes
to implementations and tests. Consult [docs/architecture.md](docs/architecture.md)
for the agent loop and ownership boundaries. Search
[docs/generated/code-index.json](docs/generated/code-index.json) for exact symbol
locations; do not rediscover the entire repository for a focused change.

Application code uses the flat `klipperai_agent/` package. There is no `src/`
wrapper. Preserve unrelated staged/unstaged changes. Python 3.10 and Pydantic v1
remain supported; avoid adding Rust-backed runtime dependencies for printer hosts.

Use composition and narrow protocols at I/O boundaries. Keep pure text transforms
as functions; do not add inheritance or classes solely to namespace utilities.
Prefer modules below roughly 350 lines and split by responsibility. Agent tools
must validate arguments, be read-only, and return evidence. Never expose a shell,
arbitrary file reader, printer motion, heaters, restarts, or writes through model
arguments. Config proposals remain review-only.

`domain/` owns evidence, investigations and proposals and must not import outer
packages. Agent code uses the read-only ports in `agent/ports.py`; it must not
import provider, infrastructure, web, API-contract or legacy-workflow modules.
The project map generator checks these boundaries. See
[docs/investigations.md](docs/investigations.md) before changing memory or review.
Printer edits are manual: never add apply/approve/restart endpoints. Persist only
public outcomes/evidence in application storage, never hidden model reasoning.

Before finishing:

1. Run `python -m pytest` (100% statement coverage is required; do not lower it).
   If Windows temp/cache permissions interfere, use
   `python -m pytest -p no:cacheprovider --basetemp=.local/test-run-N` with a fresh N.
2. Run `ruff check klipperai_agent tests tools` and `ruff format --check klipperai_agent tests tools`.
3. Run `mypy klipperai_agent --ignore-missing-imports`.
4. After changing Python code, run `python tools/project_map.py`, then
   `python tools/project_map.py --check`. The generator also rejects import cycles.
5. For packaging changes, build and smoke-test an installed wheel outside the checkout.
6. Report offline tests, browser checks, live provider checks and live printer
   checks separately. Never imply that fixtures prove real printer/provider behavior.

For a new tool, follow [docs/agent-development.md](docs/agent-development.md).
For layout migration details, see [docs/refactoring.md](docs/refactoring.md).
