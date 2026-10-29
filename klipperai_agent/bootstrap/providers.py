"""Provider composition; persisted settings take effect only on service startup."""

from __future__ import annotations

import os
from pathlib import Path

from pydantic import SecretStr

from klipperai_agent.application.providers import ProviderManagement
from klipperai_agent.domain.provider_settings import ModelProfile, ProviderPolicy
from klipperai_agent.infrastructure.provider_store import ProviderStore
from klipperai_agent.providers.credentials import OpenAICredentialValidator
from klipperai_agent.providers.usage import UsageGuard
from klipperai_agent.runtime.logging import register_provider_secret
from klipperai_agent.runtime.settings import Settings


def provider_management(settings: Settings) -> tuple[ProviderManagement, UsageGuard]:
    store = ProviderStore(
        settings.provider_storage_dir,
        (
            settings.project_checkout_path,
            Path(__file__).resolve().parents[2],
            settings.mainsail_config_dir,
            settings.printer_data_root / "config",
            settings.printer_data_root / "gcodes",
            settings.host_logs_dir(),
        ),
    )
    profile = ModelProfile(
        model=settings.openai_model, max_output_tokens=settings.agent_max_output_tokens
    )
    policy = ProviderPolicy(
        agent=profile,
        search=profile,
        knowledge=profile,
        legacy=profile,
        web_search_enabled=settings.web_search_enabled,
    )
    guard = UsageGuard(store, policy)
    manager = ProviderManagement(
        store,
        policy,
        settings.openai_api_key.get_secret_value() if settings.openai_api_key else None,
        OpenAICredentialValidator(guard),
    )
    if manager.active_revision == 0 and manager.active_key:
        store.save(0, manager.active_policy, manager.active_key)
        manager = ProviderManagement(store, policy, None, manager.validator)
    guard.policy = manager.active_policy
    register_provider_secret(manager.active_key)
    manager.environment_key = None
    for name in ("KLIPPERAI_OPENAI_API_KEY", "OPENAI_API_KEY", "KLIPPYAI_OPENAI_API_KEY"):
        os.environ.pop(name, None)
    return manager, guard


def effective_settings(settings: Settings, manager: ProviderManagement) -> Settings:
    return settings.copy(
        update={
            "llm_provider": manager.active_policy.provider,
            "openai_model": manager.active_policy.agent.model,
            "openai_api_key": SecretStr(manager.active_key) if manager.active_key else None,
            "web_search_enabled": manager.active_policy.web_search_enabled,
        }
    )
