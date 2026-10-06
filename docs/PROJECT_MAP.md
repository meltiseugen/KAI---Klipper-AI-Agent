# Project map

Read this file first when changing the project. Use the task table to narrow the
search, then inspect the implementation and its tests.

| Change | Start here | Tests |
| --- | --- | --- |
| Agent decisions, stopping, recovery | `agent/runner.py`, `agent/models.py`, `agent/prompts.py` | `test_agent.py` |
| Investigation history, cross-chat memory, deletion | `domain/investigation.py`, `application/investigations.py`, `infrastructure/investigations.py` | `test_investigations.py` |
| Manual proposal review and stale revisions | `domain/proposals.py`, `config/review.py`, `application/proposal_review.py`, `web/investigations.py` | `test_proposal_review.py`, `test_investigations.py` |
| Shared domain and read-only boundaries | `domain/`, `agent/ports.py`, `tools/project_map.py` | Full suite and project map checks |
| Add a capability | `agent/tools/`, `agent/registry.py`, `agent/workflow.py` | `test_agent.py`, `test_agent_integration.py` |
| OpenAI request/response protocol | `providers/responses.py` | `test_agent_providers.py` |
| Search and web citations | `providers/web_search.py`, `agent/tools/search.py` | `test_agent_providers.py` |
| Chat/history/session behavior | `application/chat.py`, `request_context.py`, `sessions.py` | `test_services.py`, `test_sessions.py` |
| Streaming and HTTP/UI | `web/app.py`, `streaming.py`, `static/agent.js`, `static/embed.js` | `test_app.py`, `test_agent_integration.py` |
| Settings, flags, defaults | `runtime/settings.py`, `deployment/config/klipperai.cfg.example`, `install.sh` | `test_settings.py` |
| Dependency creation/shutdown | `bootstrap/container.py` | `test_container.py`, `test_agent_integration.py` |
| Active includes and placeholders | `config/collector.py`, `parser.py`, `models.py` | `test_printerconfig*.py` |
| Macro/section identification | `config/targeting.py`, `macro_names.py`, `lookup.py` | `test_printerconfig*.py`, `test_intent_extra.py` |
| Offline config proposal templates | `config/templates/catalog.py` and feature strategies | `test_llm_config.py`, `test_llm_extra.py` |
| Runtime fault detections | `diagnostics/rules.py`, `collector.py` | `test_rules.py`, `test_diagnostics_extra.py` |
| Log/systemd collection | `infrastructure/host/` | `test_hostlogs.py`, `test_hostsystem.py` |
| Saved profile vs discovery | `profile/saved.py` vs `profile/collector.py` and detectors | `test_printerprofile*.py` |
| Preserve comments when saving profile | `profile/persistence.py` | `test_printerprofile_extra.py` |
| Moonraker API reads | `infrastructure/moonraker.py` | `test_moonraker.py` |
| Commands and installed package | `__main__.py`, `cli/`, `pyproject.toml` | `test_main.py`, `test_detect_profile.py`, `test_legacy_compat.py` |
| Mainsail / OctoEverywhere installation | `integrations/`, `install.sh`, `deployment/` | `test_octoeverywhere*.py` |

Python paths above are relative to `klipperai_agent/`; test paths are relative to
`tests/`. Top-level deployment/integration paths are relative to the repository.

## Generated discovery artifacts

- [Module index](generated/module-index.md): source links, line counts, classes/functions and direct tests.
- [Symbol index](generated/code-index.json): exact symbol lines, imports and tests, suitable for scripts and agents.
- [Import graph](generated/dependencies.mmd): Mermaid graph of package dependencies.
- [Runtime and sequence diagrams](architecture.md): actual behavior and ownership.
- [Agent extension guide](agent-development.md): adding tools/providers and validating a change.
- [Investigation lifecycle](investigations.md): memory behavior, storage bounds and manual proposal reviews.
- [Decision record](decisions/001-investigations-and-manual-review.md): why persistence and manual-only editing were chosen.
- [Migration guide](refactoring.md): old module to new owner mapping and verification commands.

Regenerate with `python tools/project_map.py`; verify with
`python tools/project_map.py --check`. Regenerate a stale index before using its
line numbers. Actual source remains authoritative.
