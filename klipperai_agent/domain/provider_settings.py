"""Public provider policy and write-only credential updates."""

from __future__ import annotations

from typing import Literal, Protocol

from pydantic import BaseModel, Field, SecretStr, validator


class ModelProfile(BaseModel):
    model: str = Field(default="gpt-5.4-mini", regex=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,119}$")
    max_output_tokens: int = Field(default=6000, ge=256, le=16000)
    reasoning_effort: Literal["default", "none", "minimal", "low", "medium", "high"] = "default"

    class Config:
        extra = "forbid"


class ProviderPolicy(BaseModel):
    provider: Literal["stub", "openai"] = "stub"
    agent: ModelProfile = Field(default_factory=ModelProfile)
    search: ModelProfile = Field(default_factory=ModelProfile)
    knowledge: ModelProfile = Field(default_factory=ModelProfile)
    legacy: ModelProfile = Field(default_factory=ModelProfile)
    requests_per_minute: int = Field(default=20, ge=1, le=120)
    requests_per_day: int = Field(default=200, ge=1, le=10000)
    tokens_per_day: int = Field(default=2_000_000, ge=1000, le=100_000_000)
    max_concurrent_requests: int = Field(default=2, ge=1, le=8)
    web_search_enabled: bool = True

    class Config:
        extra = "forbid"


class ProviderUpdate(BaseModel):
    session_id: str = Field(min_length=1, max_length=200)
    revision: int = Field(ge=0)
    policy: ProviderPolicy
    api_key: SecretStr | None = None
    remove_key: bool = False

    @validator("api_key")
    def valid_key(cls, value: SecretStr | None) -> SecretStr | None:
        if value is not None:
            text = value.get_secret_value()
            if not 8 <= len(text) <= 512 or any(not 33 <= ord(char) <= 126 for char in text):
                raise ValueError("Enter a key without whitespace or control characters.")
        return value

    class Config:
        extra = "forbid"


class ProviderConflict(ValueError):
    """A settings editor is stale."""


class ProviderLimitError(RuntimeError):
    """A local usage guard blocked a provider call."""


class ProviderRepository(Protocol):
    def load(self) -> tuple[int, ProviderPolicy | None, str | None]: ...
    def save(self, revision: int, policy: ProviderPolicy, key: str | None) -> int: ...
    def reserve(self, policy: ProviderPolicy, tokens: int) -> tuple[str, int]: ...
    def settle(self, reservation: tuple[str, int], actual: int) -> None: ...
    def cooldown(self, seconds: float) -> None: ...
    def usage(self) -> dict[str, int | str]: ...


class CredentialValidator(Protocol):
    async def validate(self, key: str, models: list[str]) -> None: ...
