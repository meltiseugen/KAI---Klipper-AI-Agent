"""Validate and atomically save provider setup without exposing credential reads."""

from __future__ import annotations

import asyncio

from klipperai_agent.domain.provider_settings import (
    CredentialValidator,
    ProviderConflict,
    ProviderPolicy,
    ProviderRepository,
    ProviderUpdate,
)


class ProviderManagement:
    def __init__(
        self,
        store: ProviderRepository,
        defaults: ProviderPolicy,
        environment_key: str | None,
        validator: CredentialValidator,
    ):
        self.store = store
        self.defaults = defaults
        self.environment_key = environment_key
        self.validator = validator
        self.active_revision, saved, key = store.load()
        self.active_policy = saved or defaults
        self.active_key = key if saved is not None else environment_key
        self._lock = asyncio.Lock()

    def status(self) -> dict:
        revision, saved, key = self.store.load()
        return {
            "revision": revision,
            "credential_storage_available": self.store.credential_storage_available,
            "policy": (saved or self.defaults).dict(),
            "active_policy": self.active_policy.dict(),
            "credential_configured": bool(key if saved else self.environment_key),
            "credential_source": "stored"
            if saved and key
            else "environment"
            if not saved and self.environment_key
            else "none",
            "active_credential_configured": bool(self.active_key),
            "restart_required": revision != self.active_revision,
            "usage": self.store.usage(),
        }

    async def update(self, update: ProviderUpdate, *, save: bool) -> dict:
        if self._lock.locked():
            raise ProviderConflict("Provider validation is already running. Try again shortly.")
        async with self._lock:
            revision, saved, key = self.store.load()
            if revision != update.revision:
                raise ProviderConflict("Provider settings changed. Reload settings before saving.")
            if update.remove_key and update.api_key:
                raise ValueError("Choose either a replacement key or removal.")
            candidate = key if saved is not None else self.environment_key
            if update.api_key:
                candidate = update.api_key.get_secret_value()
            if update.remove_key:
                candidate = None
            if not update.remove_key:
                if not candidate:
                    raise ValueError("Enter an OpenAI API key to enable the agent.")
                models = sorted(
                    {
                        getattr(update.policy, role).model
                        for role in ("agent", "search", "knowledge", "legacy")
                    }
                )
                await self.validator.validate(candidate, models)
            if save:
                self.store.save(revision, update.policy, candidate)
            return {
                **self.status(),
                "validation": "Model access checked."
                if not update.remove_key
                else "API key removal checked. The agent will be unavailable after restart.",
            }
