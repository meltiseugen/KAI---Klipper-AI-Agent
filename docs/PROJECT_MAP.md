# Project map

Read this file first when changing the project. Use the task table to narrow the
search, then inspect the implementation and its tests.

| Change | Start here | Tests |
| --- | --- | --- |
| Agent decisions, stopping, recovery | `agent/runner.py`, `agent/models.py`, `agent/prompts.py` | `test_agent.py` |
| Workflow response contracts, grounded claims and manual recovery playbooks | `agent/response_contracts.py`, `claim_citations.py`, `diagnostics/signatures.py`, `playbooks.py`, [intelligence guide](intelligence-quality.md) | `test_workflow_contracts.py`, `test_structured_citations.py`, `test_intelligence_quality.py`, `intelligence-quality-ui.test.mjs` |
| Chat/Debug modes, automatic config/log reads and context receipts | `domain/context.py`, `agent/starting_context.py`, `agent/context_budget.py`, `agent/deadline.py`, `application/chat.py`, [mode guide](agent-modes.md) | `test_agent_modes.py`, `test_automatic_context.py`, `modes-ui.test.mjs` |
| Investigation history, cross-chat memory, deletion | `domain/investigation.py`, `application/investigations.py`, `infrastructure/investigations.py` | `test_investigations.py` |
| Confirmed facts/preferences and incident resolutions | `application/investigations.py`, `infrastructure/confirmed_memory.py`, `web/memory.py`, `web/static/memory.js` | `test_confirmed_memory.py`, `memory-recovery-ui.test.mjs` |
| Interrupted requests and restart recovery | `application/recovery.py`, `application/chat.py`, `infrastructure/investigation_runs.py`, `web/static/investigation-sync.js` | `test_investigation_recovery.py`, `memory-recovery-ui.test.mjs` |
| Manual proposal review and stale revisions | `domain/proposals.py`, `config/review.py`, `application/proposal_review.py`, `web/investigations.py` | `test_proposal_review.py`, `test_investigations.py` |
| Option/version checks and manual verification | `config/option_review.py`, `option_rules.py`, `review_parser.py`, `review_versions.py`, `review_guidance.py`, `application/review_firmware.py`, `web/static/proposal-review-view.js`, [review guide](configuration-review.md) | `test_review_options.py`, `proposal-review-ui.test.mjs` |
| Shared domain and read-only boundaries | `domain/`, `agent/ports.py`, `tools/project_map.py` | Full suite and project map checks |
| Low-resource performance, idle work and bounded reads | [performance audit](performance.md), `tools/benchmark_resources.py`, `infrastructure/host/logs.py`, `config/collector.py`, `web/static/investigation-sync.js` | `test_resource_bounds.py`, `resource-ui.test.mjs` |
| Add a capability | `agent/tools/`, `agent/registry.py`, `agent/workflow.py` | `test_agent.py`, `test_agent_integration.py` |
| OpenAI request/response protocol | `providers/responses.py` | `test_agent_providers.py` |
| Search and web citations | `providers/web_search.py`, `agent/tools/search.py` | `test_agent_providers.py` |
| Chat/history/session behavior | `application/chat.py`, `request_context.py`, `sessions.py` | `test_services.py`, `test_sessions.py` |
| Streaming and HTTP/UI | `web/app.py`, `streaming.py`, `static/scripts.json`, `static/chat-application.js` | `test_app.py`, `test_agent_integration.py`, `agent-ui.test.mjs`, `chat-ui.test.mjs` |
| Browser drafts, HTTP, rendering | `web/static/store.js`, `transport.js`, `message-view.js`, `shell-view.js` | `chat-ui.test.mjs` |
| Result cards, follow-ups and recovery notices | `web/static/result-cards.js`, `ui-errors.js`, `web/chat_readiness.py`, `contracts/api.py` | `embedded-experience.test.mjs`, `test_embedded_experience.py` |
| Credential redaction, private storage and deployment trust | `domain/redaction.py`, `web/security.py`, `infrastructure/private_files.py`, `runtime/logging.py`, [security guide](security.md) | `test_security*.py`, `test_installer.py` |
| Settings, flags, defaults | `runtime/settings.py`, `deployment/config/klipperai.cfg.example`, `install.sh` | `test_settings.py` |
| Provider setup/rotation, model profiles and usage safety | `application/providers.py`, `bootstrap/providers.py`, `infrastructure/provider_store.py`, `providers/usage.py`, `web/providers.py`, `web/static/providers.js`, [provider guide](providers.md) | `test_provider_management.py`, `test_provider_web.py`, `providers-ui.test.mjs` |
| Encrypted credentials, master delivery and installer migration | `infrastructure/credential_cipher.py`, `cli/credentials.py`, `deployment/installer/credentials.sh`, [storage guide](credential-storage.md) | `test_credential_storage.py`, `test_credential_installer.py`, `test_security_deployment.py` |
| Dependency creation/shutdown | `bootstrap/container.py` | `test_container.py`, `test_agent_integration.py` |
| Active includes and placeholders | `config/collector.py`, `parser.py`, `models.py` | `test_printerconfig*.py` |
| Active config audits, managed fragments and manual file patches | `config/analysis.py`, `config/patches.py`, `agent/tools/config_analysis.py`, [assistant guide](config-assistant.md) | `test_config_analysis.py`, `test_config_patches.py`, `config-assistant-ui.test.mjs` |
| Parameterized probe, mesh, shaper and status macro drafts | `config/templates/features.py`, `config/templates/catalog.py` | `test_config_features.py` |
| Start/end/preflight macros, BLTouch and accelerometer/resonance drafts | `config/templates/advanced.py`, `config/templates/catalog.py`, [hardware guide](hardware-knowledge.md) | `test_advanced_templates.py` |
| Macro/section identification | `config/targeting.py`, `macro_names.py`, `lookup.py` | `test_printerconfig*.py`, `test_intent_extra.py` |
| Model-requested config template guidance | `agent/tools/config_templates.py`, `config/templates/catalog.py` and feature strategies | `test_llm_config.py`, `test_llm_extra.py`, `test_config_templates_agent.py` |
| LLM readiness, request progress and saved usage receipts | `web/chat_readiness.py`, `runtime/model_usage.py`, `domain/model_usage.py`, `web/static/model-usage.js` | `test_model_usage.py`, `model-usage-ui.test.mjs` |
| Runtime fault detections | `diagnostics/rules.py`, `collector.py`, [rule coverage and evidence](runtime-diagnostics.md) | `test_rules.py`, `test_runtime_rules.py`, `test_runtime_diagnostics.py`, `test_diagnostics_extra.py` |
| Typed collected context, API evidence blocks and finding confidence/ranks | `domain/artifacts.py`, `domain/evidence.py`, `diagnostics/evidence.py`, `application/chat_response.py`, [evidence contract](evidence-contract.md) | `test_typed_artifacts.py`, `test_evidence_pipeline.py` |
| USB/CAN shutdowns, pre-stop statistics and kernel correlation | `domain/shutdown.py`, `diagnostics/shutdown*.py`, `infrastructure/host/shutdown*.py`, `agent/tools/shutdown.py`, [investigation guide](shutdown-investigations.md) | `test_shutdown.py`, `test_shutdown_host.py`, `test_shutdown_agent.py` |
| Log/systemd collection | `infrastructure/host/` | `test_hostlogs.py`, `test_hostsystem.py` |
| Read-only log/config search, match context and older windows | [search tools](log-and-config-search.md), `agent/tools/logs.py`, `text_search.py`, `config_search.py`, `infrastructure/host/log_reader.py`, `domain/logs.py` | `test_agent_search.py`, `test_log_reader.py`, `test_text_search.py` |
| Opt-in host flight recorder, pressure history and broader journals | `domain/host_history.py`, `infrastructure/host/proc.py`, `history_store.py`, `flight_recorder.py`, [host guide](host-diagnostics.md) | `test_host_flight_recorder.py`, `test_diagnostics_mvp.py` |
| Core Moonraker diagnostic state and sourced incident replay | `infrastructure/moonraker_state.py`, `tools/validate_shutdown.py`, `tests/fixtures/shutdown/cases.json` | `test_diagnostics_mvp.py`, `test_shutdown_validation.py` |
| Saved profile vs discovery | `profile/saved.py` vs `profile/collector.py` and detectors | `test_printerprofile*.py` |
| Dynamic component research, cached manuals, fan pins and Eddy calibration evidence | `knowledge/`, `application/knowledge.py`, `providers/knowledge.py`, `infrastructure/knowledge.py`, `infrastructure/documentation.py`, `infrastructure/public_docs.py`, `agent/tools/knowledge.py`, `web/knowledge.py`, `web/static/knowledge.js`, [knowledge guide](printer-knowledge.md) | `test_knowledge*.py`, `knowledge-ui.test.mjs` |
| Reviewed bus pins, physical connector inventory, PDF page/diagram index and exact-commit references | `domain/hardware.py`, `knowledge/buses.py`, `firmware.py`, `pdf_pages.py`, `infrastructure/pdf_index.py`, `application/knowledge_observations.py`, `knowledge_refresh.py`, `web/static/knowledge-actions.js`, [hardware guide](hardware-knowledge.md) | `test_hardware_knowledge.py`, `test_firmware_knowledge.py`, `test_pdf_knowledge.py`, `hardware-knowledge-ui.test.mjs` |
| Component-family diagnostics and explicit live validation | `agent/tools/components.py`, `knowledge/components.py`, `application/hardware_validation.py`, `providers/probe.py` | `test_hardware_knowledge.py`, `test_live_hardware_validation.py` |
| Preserve comments when saving profile | `profile/persistence.py` | `test_printerprofile_extra.py` |
| Moonraker API reads | `infrastructure/moonraker.py` | `test_moonraker.py` |
| Moonraker registration, printer events, extension methods and file metadata | `domain/moonraker.py`, `application/moonraker.py`, `infrastructure/moonraker_agent.py`, `infrastructure/moonraker_rpc.py`, `agent/tools/file_metadata.py`, `web/moonraker.py`, `web/static/moonraker.js`, [integration guide](moonraker-integration.md) | `test_moonraker_extension.py`, `test_moonraker_rpc.py`, `test_moonraker_metadata.py`, `test_moonraker_web.py`, `moonraker-ui.test.mjs` |
| Commands and installed package | `__main__.py`, `cli/`, `pyproject.toml` | `test_main.py`, `test_detect_profile.py`, `test_legacy_compat.py` |
| Guided install, Mainsail navigation, nginx | `install.sh`, `deployment/installer/modules.txt`, `integrations/mainsail/` | `test_installer.py` |
| Automatic prerequisite installation, BusyBox startup and fresh Entware bootstrap | `deployment/installer/bootstrap.sh`, `entware.sh`, `prerequisites.sh`, [prerequisites](installer-prerequisites.md) | `test_prerequisite_bootstrap.py`, `test_entware_bootstrap.py` |
| Creality/KE native init, host credentials, vendor paths and Python/nginx fallbacks | `deployment/appliance_*.py`, `deployment/installer/platform.sh`, `discovery.sh`, `python.sh`, `nginx.sh`, [native guide](creality-compatibility.md) | `test_appliance_*.py`, `test_native_host_boot.py`, `test_creality_compatibility.py`, `test_installer.py` |
| Linux CI, installed daemon boot and actual nginx routing | `.github/workflows/linux.yml`, `tools/smoke_installed.py`, [release guide](RELEASING.md) | `test_release_integration.py`, `test_nginx_smoke.py` |
| Operator SSH updates, staged code and rollback | `tools/deploy.py`, `deployment/update.py`, `deployment/releases.py`, `deployment/artifacts.py`, [printer testing](printer-testing.md) | `test_deploy.py`, `test_release_updates.py`, `test_release_artifacts.py` |
| Version, release contents and failure examples | `domain/version.py`, `runtime/release.py`, `tools/release_artifacts.py`, `CHANGELOG.md`, `examples/failures/` | `test_release_identity.py`, `test_release_artifacts.py`, `test_failure_examples.py` |
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
