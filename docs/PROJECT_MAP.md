# Project map

Read this file first when changing the project. Use the task table to narrow the
search, then inspect the implementation and its tests.

| Change | Start here | Tests |
| --- | --- | --- |
| Agent decisions, stopping, recovery | `agent/runner.py`, `agent/models.py`, `agent/prompts.py` | `test_agent.py` |
| Chat/Debug modes and context receipts | `domain/context.py`, `agent/starting_context.py`, `agent/context_budget.py`, `agent/deadline.py`, `application/chat.py`, [mode guide](agent-modes.md) | `test_agent_modes.py`, `modes-ui.test.mjs` |
| Investigation history, cross-chat memory, deletion | `domain/investigation.py`, `application/investigations.py`, `infrastructure/investigations.py` | `test_investigations.py` |
| Manual proposal review and stale revisions | `domain/proposals.py`, `config/review.py`, `application/proposal_review.py`, `web/investigations.py` | `test_proposal_review.py`, `test_investigations.py` |
| Shared domain and read-only boundaries | `domain/`, `agent/ports.py`, `tools/project_map.py` | Full suite and project map checks |
| Add a capability | `agent/tools/`, `agent/registry.py`, `agent/workflow.py` | `test_agent.py`, `test_agent_integration.py` |
| OpenAI request/response protocol | `providers/responses.py` | `test_agent_providers.py` |
| Search and web citations | `providers/web_search.py`, `agent/tools/search.py` | `test_agent_providers.py` |
| Chat/history/session behavior | `application/chat.py`, `request_context.py`, `sessions.py` | `test_services.py`, `test_sessions.py` |
| Streaming and HTTP/UI | `web/app.py`, `streaming.py`, `static/scripts.json`, `static/chat-application.js` | `test_app.py`, `test_agent_integration.py`, `agent-ui.test.mjs`, `chat-ui.test.mjs` |
| Browser drafts, HTTP, rendering | `web/static/store.js`, `transport.js`, `message-view.js`, `shell-view.js` | `chat-ui.test.mjs` |
| Credential redaction, private storage and deployment trust | `domain/redaction.py`, `web/security.py`, `infrastructure/private_files.py`, `runtime/logging.py`, [security guide](security.md) | `test_security*.py`, `test_installer.py` |
| Settings, flags, defaults | `runtime/settings.py`, `deployment/config/klipperai.cfg.example`, `install.sh` | `test_settings.py` |
| Provider setup/rotation, model profiles and usage safety | `application/providers.py`, `bootstrap/providers.py`, `infrastructure/provider_store.py`, `providers/usage.py`, `web/providers.py`, `web/static/providers.js`, [provider guide](providers.md) | `test_provider_management.py`, `test_provider_web.py`, `providers-ui.test.mjs` |
| Dependency creation/shutdown | `bootstrap/container.py` | `test_container.py`, `test_agent_integration.py` |
| Active includes and placeholders | `config/collector.py`, `parser.py`, `models.py` | `test_printerconfig*.py` |
| Macro/section identification | `config/targeting.py`, `macro_names.py`, `lookup.py` | `test_printerconfig*.py`, `test_intent_extra.py` |
| Offline config proposal templates | `config/templates/catalog.py` and feature strategies | `test_llm_config.py`, `test_llm_extra.py` |
| Runtime fault detections | `diagnostics/rules.py`, `collector.py` | `test_rules.py`, `test_diagnostics_extra.py` |
| USB/CAN shutdowns, pre-stop statistics and kernel correlation | `domain/shutdown.py`, `diagnostics/shutdown*.py`, `infrastructure/host/shutdown*.py`, `agent/tools/shutdown.py`, [investigation guide](shutdown-investigations.md) | `test_shutdown.py`, `test_shutdown_host.py`, `test_shutdown_agent.py` |
| Log/systemd collection | `infrastructure/host/` | `test_hostlogs.py`, `test_hostsystem.py` |
| Saved profile vs discovery | `profile/saved.py` vs `profile/collector.py` and detectors | `test_printerprofile*.py` |
| Dynamic component research, cached manuals, fan pins and Eddy calibration evidence | `knowledge/`, `application/knowledge.py`, `providers/knowledge.py`, `infrastructure/knowledge.py`, `infrastructure/documentation.py`, `infrastructure/public_docs.py`, `agent/tools/knowledge.py`, `web/knowledge.py`, `web/static/knowledge.js`, [knowledge guide](printer-knowledge.md) | `test_knowledge*.py`, `knowledge-ui.test.mjs` |
| Preserve comments when saving profile | `profile/persistence.py` | `test_printerprofile_extra.py` |
| Moonraker API reads | `infrastructure/moonraker.py` | `test_moonraker.py` |
| Moonraker registration, printer events, extension methods and file metadata | `domain/moonraker.py`, `application/moonraker.py`, `infrastructure/moonraker_agent.py`, `infrastructure/moonraker_rpc.py`, `agent/tools/file_metadata.py`, `web/moonraker.py`, `web/static/moonraker.js`, [integration guide](moonraker-integration.md) | `test_moonraker_extension.py`, `test_moonraker_rpc.py`, `test_moonraker_metadata.py`, `test_moonraker_web.py`, `moonraker-ui.test.mjs` |
| Commands and installed package | `__main__.py`, `cli/`, `pyproject.toml` | `test_main.py`, `test_detect_profile.py`, `test_legacy_compat.py` |
| Guided install, Mainsail navigation, nginx | `install.sh`, `deployment/installer/modules.txt`, `integrations/mainsail/` | `test_installer.py` |
| Mainsail sidebar repair at boot and after theme changes | `integrations/mainsail/navigation.py`, `navigation_file.py`, `nav_cli.py`, `nav_hook.py`, `integrations/host_lock.py` | `test_mainsail_navigation.py`, `test_mainsail_auto_reapply.py`, `test_installer.py` |
| OctoEverywhere routing and update coordination | `integrations/octoeverywhere/route_patch.py`, `router.template`, `navigation.js`, `maintenance.py`, `patch_files.py`, `maintenance_state.py`, `update_coordinator.py`, `install-auto-reapply.sh` | `test_octoeverywhere*.py`, `octoeverywhere-ui.test.mjs` |

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
- [Frontend and installer map](frontend-and-installation.md): script ownership, proxy routes, optional integrations and regression checks.

Regenerate with `python tools/project_map.py`; verify with
`python tools/project_map.py --check`. Regenerate a stale index before using its
line numbers. Actual source remains authoritative.
