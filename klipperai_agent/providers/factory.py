from __future__ import annotations

from klipperai_agent.application.intent import IntentRouterProvider
from klipperai_agent.domain.provider_settings import ModelProfile
from klipperai_agent.providers.config_stub import StubConfigAssistantProvider
from klipperai_agent.providers.models import ConfigAssistantProvider, DiagnosisProvider
from klipperai_agent.providers.openai import (
    OpenAIConfigAssistantProvider,
    OpenAIDiagnosisProvider,
    OpenAIIntentRouterProvider,
)
from klipperai_agent.providers.stub import (
    StubDiagnosisProvider,
    StubIntentRouterProvider,
)
from klipperai_agent.providers.usage import UsageGuard
from klipperai_agent.runtime.settings import Settings


def build_diagnosis_provider(
    settings: Settings, *, guard: UsageGuard | None = None, profile: ModelProfile | None = None
) -> DiagnosisProvider:
    provider = settings.llm_provider.lower().strip()
    if provider == "openai":
        api_key = settings.openai_api_key.get_secret_value() if settings.openai_api_key else None
        return OpenAIDiagnosisProvider(
            model=settings.openai_model,
            api_key=api_key,
            guard=guard,
            profile=profile,
        )
    return StubDiagnosisProvider()


def build_config_provider(
    settings: Settings, *, guard: UsageGuard | None = None, profile: ModelProfile | None = None
) -> ConfigAssistantProvider:
    provider = settings.llm_provider.lower().strip()
    if provider == "openai":
        api_key = settings.openai_api_key.get_secret_value() if settings.openai_api_key else None
        return OpenAIConfigAssistantProvider(
            model=settings.openai_model,
            api_key=api_key,
            guard=guard,
            profile=profile,
        )
    return StubConfigAssistantProvider()


def build_intent_router(
    settings: Settings, *, guard: UsageGuard | None = None, profile: ModelProfile | None = None
) -> IntentRouterProvider:
    provider = settings.llm_provider.lower().strip()
    if provider == "openai":
        api_key = settings.openai_api_key.get_secret_value() if settings.openai_api_key else None
        return OpenAIIntentRouterProvider(
            model=settings.openai_model,
            api_key=api_key,
            guard=guard,
            profile=profile,
        )
    return StubIntentRouterProvider()
