import asyncio
import json
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import ValidationError

from klipperai_agent.application.providers import ProviderManagement
from klipperai_agent.bootstrap.providers import effective_settings, provider_management
from klipperai_agent.domain.provider_settings import (
    ModelProfile,
    ProviderConflict,
    ProviderLimitError,
    ProviderPolicy,
    ProviderUpdate,
)
from klipperai_agent.infrastructure.provider_store import ProviderStore
from klipperai_agent.providers.credentials import OpenAICredentialValidator
from klipperai_agent.providers.json_client import OpenAIJsonClient
from klipperai_agent.providers.responses import ProviderError, ResponsesClient
from klipperai_agent.providers.usage import UsageGuard
from klipperai_agent.runtime.settings import Settings


def store_at(tmp_path):
    return ProviderStore(tmp_path / "private", (tmp_path / "checkout", tmp_path / "config"))


def update(**values):
    return ProviderUpdate(session_id="session", revision=0, policy=ProviderPolicy(), **values)


@pytest.mark.asyncio
async def test_setup_validation_rotation_removal_and_restart(tmp_path):
    store = store_at(tmp_path)
    validator = SimpleNamespace(validate=AsyncMock())
    manager = ProviderManagement(store, ProviderPolicy(), "environment-secret", validator)
    assert manager.status()["credential_source"] == "environment"
    checked = await manager.update(update(), save=False)
    assert checked["validation"] == "Model access checked."
    validator.validate.assert_awaited_once()
    request = update(api_key="replacement-secret")
    request.policy.provider = "openai"
    request.policy.search = ModelProfile(model="search-model", max_output_tokens=500)
    checked = await manager.update(request, save=False)
    assert checked["revision"] == 0 and not checked["restart_required"]
    assert store.load() == (0, None, None)
    saved = await manager.update(request, save=True)
    assert saved["restart_required"] and saved["credential_source"] == "stored"
    assert "replacement-secret" not in json.dumps(saved)
    assert manager.active_key == "environment-secret"
    validator.validate.assert_awaited_with("replacement-secret", ["gpt-5.4-mini", "search-model"])
    with pytest.raises(ProviderConflict):
        await manager.update(request, save=True)
    with pytest.raises(ProviderConflict):
        store.save(0, request.policy, "stale")
    restarted = ProviderManagement(store_at(tmp_path), ProviderPolicy(), "old-env", validator)
    assert restarted.active_key == "replacement-secret"
    assert not restarted.status()["restart_required"]
    request.revision = 1
    request.api_key = None
    await restarted.update(request, save=True)
    assert store.load()[2] == "replacement-secret"
    request.revision = 2
    request.remove_key = True
    assert not (await restarted.update(request, save=True))["credential_configured"]
    removed = ProviderManagement(store, ProviderPolicy(), "old-env", validator)
    assert removed.active_key is None and removed.status()["credential_source"] == "none"
    if os.name != "nt":
        assert store.path.stat().st_mode & 0o777 == 0o600
        assert store.path.parent.stat().st_mode & 0o777 == 0o700


@pytest.mark.asyncio
async def test_failed_validation_and_concurrent_edit_preserve_active_settings(tmp_path):
    validator = SimpleNamespace(validate=AsyncMock(side_effect=ValueError("rejected")))
    manager = ProviderManagement(store_at(tmp_path), ProviderPolicy(), None, validator)
    with pytest.raises(ValueError, match="API key"):
        await manager.update(update(), save=True)
    request = update(api_key="valid-shape-key")
    with pytest.raises(ValueError, match="rejected"):
        await manager.update(request, save=True)
    assert manager.store.load()[0] == 0
    request.remove_key = True
    with pytest.raises(ValueError, match="either"):
        await manager.update(request, save=True)
    async with manager._lock:
        with pytest.raises(ProviderConflict, match="already running"):
            await manager.update(request, save=False)
    validator.validate = AsyncMock(
        side_effect=lambda *args: manager.store.save(0, ProviderPolicy(), None)
    )
    request.remove_key = False
    with pytest.raises(ProviderConflict):
        await manager.update(request, save=True)


@pytest.mark.parametrize("key", ["tiny", "has space key", "newline\nkey", "é" * 12, "a" * 513])
def test_secret_input_validation_never_prints_key(key):
    with pytest.raises(ValidationError) as error:
        update(api_key=key)
    assert key not in str(error.value)
    assert update(api_key=None).api_key is None
    assert "valid-shape-key" not in repr(update(api_key="valid-shape-key"))


def test_storage_rejects_checkout_special_and_redirected_files(tmp_path, monkeypatch):
    with pytest.raises(ValueError, match="private"):
        ProviderStore(tmp_path / "config" / "secrets", (tmp_path / "config",))
    store = store_at(tmp_path)
    auxiliary = store.path.with_name(store.path.name + "-wal")
    auxiliary.mkdir()
    with pytest.raises(ValueError):
        store.load()
    auxiliary.rmdir()
    original = type(store.path).is_symlink
    monkeypatch.setattr(
        type(store.path), "is_symlink", lambda path: path == store.path.parent or original(path)
    )
    with pytest.raises(ValueError):
        store.load()


def test_usage_reservations_are_atomic_persistent_and_do_not_reset_on_rotation(
    tmp_path, monkeypatch
):
    store = store_at(tmp_path)
    policy = ProviderPolicy(requests_per_minute=2, requests_per_day=3, tokens_per_day=1000)
    first = store.reserve(policy, 800)
    with pytest.raises(ProviderLimitError, match="Daily"):
        store.reserve(policy, 201)
    store.settle(first, 100)
    store.reserve(policy, 100)
    with pytest.raises(ProviderLimitError, match="per minute"):
        store_at(tmp_path).reserve(policy, 1)
    store.save(0, policy, "new-secret")
    assert store.usage()["requests"] == 2 and store.usage()["tokens"] == 200
    policy.requests_per_minute = 10
    store.reserve(policy, 1)
    with pytest.raises(ProviderLimitError, match="Daily"):
        store.reserve(policy, 1)
    store.cooldown(60)
    with pytest.raises(ProviderLimitError, match="cooldown"):
        store.reserve(policy, 1)
    import klipperai_agent.infrastructure.provider_store as module

    now = module.time.time()
    monkeypatch.setattr(module.time, "time", lambda: now + 86400)
    assert store.reserve(policy, 1)[0] != first[0]


@pytest.mark.asyncio
async def test_guard_concurrency_cancellation_unknown_usage_and_throttle(tmp_path):
    store = store_at(tmp_path)
    guard = UsageGuard(store, ProviderPolicy(max_concurrent_requests=1))
    async with guard.request({"input": "test"}, 256) as reservation:
        with pytest.raises(ProviderLimitError, match="already running"):
            async with guard.request({}, 256):
                pytest.fail("Must not send concurrent request")
        for data in (
            None,
            {},
            {"usage": {}},
            {"usage": {"total_tokens": True}},
            {"usage": {"total_tokens": -1}},
        ):
            guard.record(reservation, data)
        assert store.usage()["tokens"] > 256
        guard.record(reservation, {"usage": {"total_tokens": 23}})
    assert guard.active == 0 and store.usage()["tokens"] == 23
    with pytest.raises(asyncio.CancelledError):
        async with guard.request({}, 300):
            raise asyncio.CancelledError()
    assert guard.active == 0 and store.usage()["tokens"] > 300
    guard.throttle("invalid")
    guard.throttle("2")
    with pytest.raises(ProviderLimitError, match="cooldown"):
        async with guard.request({}, 1):
            pytest.fail("Must not send during cooldown")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status,data,message",
    [
        (401, {}, "rejected"),
        (403, {}, "rejected"),
        (404, {}, "unavailable"),
        (429, {}, "rate limit"),
        (500, {}, "reach"),
        (200, {}, "unexpected"),
        (200, [], "unexpected"),
        (200, {"id": "model-a"}, None),
    ],
)
async def test_credential_validation_uses_fixed_read_only_endpoint(tmp_path, status, data, message):
    guard = UsageGuard(store_at(tmp_path), ProviderPolicy())

    def handler(request):
        assert str(request.url) == "https://api.openai.com/v1/models/model-a"
        assert request.method == "GET" and request.headers["Authorization"] == "Bearer private-key"
        return httpx.Response(status, json=data)

    validator = OpenAICredentialValidator(guard, httpx.MockTransport(handler))
    if message:
        with pytest.raises(ValueError, match=message):
            await validator.validate("private-key", ["model-a"])
    else:
        await validator.validate("private-key", ["model-a"])
    assert guard.store.usage()["requests"] == 1 and guard.store.usage()["tokens"] == 0


@pytest.mark.asyncio
async def test_model_routing_caps_redaction_and_actual_usage(tmp_path):
    policy = ProviderPolicy(
        agent=ModelProfile(model="agent-model", max_output_tokens=500),
        search=ModelProfile(model="search-model", max_output_tokens=300, reasoning_effort="low"),
        knowledge=ModelProfile(model="research-model", max_output_tokens=400),
    )
    guard = UsageGuard(store_at(tmp_path), policy)
    sent = []

    def handler(request):
        sent.append(json.loads(request.content))
        return httpx.Response(
            200, json={"status": "completed", "output": [], "usage": {"total_tokens": 10}}
        )

    client = ResponsesClient(
        "ignored", "private-key", guard=guard, policy=policy, transport=httpx.MockTransport(handler)
    )
    try:
        for purpose in ("agent", "search", "knowledge"):
            await client.create(
                purpose=purpose,
                input="private-key",
                max_output_tokens=15000,
                model="bypass",
                store=True,
            )
        assert [x["model"] for x in sent] == ["agent-model", "search-model", "research-model"]
        assert [x["max_output_tokens"] for x in sent] == [500, 300, 400]
        assert sent[1]["reasoning"] == {"effort": "low"}
        assert all(x["store"] is False and "private-key" not in json.dumps(x) for x in sent)
        assert guard.store.usage()["tokens"] == 30
        with pytest.raises(ProviderError, match="Unknown"):
            await client.create(purpose="unknown")
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_responses_and_legacy_share_budget_and_cooldown(tmp_path, monkeypatch):
    guard = UsageGuard(store_at(tmp_path), ProviderPolicy())
    client = ResponsesClient(
        "model",
        "private-key",
        guard=guard,
        transport=httpx.MockTransport(
            lambda _: httpx.Response(429, headers={"retry-after": "120"})
        ),
    )
    try:
        with pytest.raises(ProviderError):
            await client.create(input="test")
        legacy = OpenAIJsonClient("model", "private-key", guard=guard)
        with pytest.raises(ProviderLimitError, match="cooldown"):
            await legacy.complete_json(system_prompt="JSON", user_prompt="test")
    finally:
        await client.aclose()
    guard = UsageGuard(ProviderStore(tmp_path / "second", ()), ProviderPolicy())
    sent = []

    def handler(request):
        sent.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": '{"ok": true}'}}],
                "usage": {"total_tokens": 12},
            },
        )

    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: real_client(**kwargs, transport=httpx.MockTransport(handler)),
    )
    legacy = OpenAIJsonClient(
        "model",
        "private-key",
        guard=guard,
        profile=ModelProfile(model="legacy-model", max_output_tokens=500, reasoning_effort="low"),
    )
    assert await legacy.complete_json(system_prompt="JSON", user_prompt="test") == {"ok": True}
    assert sent[0]["max_completion_tokens"] == 500 and sent[0]["reasoning_effort"] == "low"
    assert guard.store.usage()["tokens"] == 12
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: real_client(
            **kwargs, transport=httpx.MockTransport(lambda _: httpx.Response(429))
        ),
    )
    with pytest.raises(httpx.HTTPStatusError):
        await legacy.complete_json(system_prompt="JSON", user_prompt="test")


def test_bootstrap_loads_private_policy_over_environment_and_blocks_repo_storage(tmp_path):
    settings = Settings(provider_storage_dir=tmp_path / "private", openai_api_key="environment-key")
    manager, guard = provider_management(settings)
    policy = ProviderPolicy(
        provider="openai", web_search_enabled=False, agent=ModelProfile(model="selected-model")
    )
    manager.store.save(manager.active_revision, policy, "stored-key")
    restarted, guard = provider_management(settings)
    effective = effective_settings(settings, restarted)
    assert effective.openai_api_key.get_secret_value() == "stored-key"
    assert effective.openai_model == "selected-model" and effective.llm_provider == "openai"
    assert not effective.web_search_enabled and guard.policy == policy
    restarted.store.save(restarted.active_revision, ProviderPolicy(), None)
    removed, _ = provider_management(settings)
    assert effective_settings(settings, removed).openai_api_key is None
    with pytest.raises(ValueError):
        provider_management(
            Settings(provider_storage_dir=settings.project_checkout_path / "secrets")
        )


def test_retired_provider_settings_never_activate_an_old_key_or_discard_saved_policy(tmp_path):
    import sqlite3
    from contextlib import closing

    settings = Settings(llm_provider="retired-provider", openai_api_key="unused-key")
    assert settings.llm_provider == "openai" and settings.openai_api_key is None
    store = store_at(tmp_path)
    store.save(0, ProviderPolicy(requests_per_day=77), "preserved-key")
    with closing(sqlite3.connect(store.path)) as db, db:
        policy = json.loads(db.execute("SELECT policy FROM settings").fetchone()[0])
        policy["provider"] = "retired-provider"
        db.execute("UPDATE settings SET policy=?", (json.dumps(policy),))
        original = db.execute("SELECT api_key FROM settings").fetchone()[0]
    revision, normalized, key = store.load()
    assert revision == 1 and normalized.provider == "openai"
    assert normalized.requests_per_day == 77 and key is None
    with closing(sqlite3.connect(store.path)) as db:
        assert db.execute("SELECT api_key FROM settings").fetchone()[0] == original
    assert Settings().llm_provider == "openai"


def test_private_store_key_is_added_to_runtime_log_redaction(monkeypatch):
    import logging

    from klipperai_agent.runtime.logging import RedactingFormatter, register_provider_secret

    handler = logging.StreamHandler()
    formatter = RedactingFormatter("old-key")
    handler.setFormatter(formatter)
    monkeypatch.setattr(logging.getLogger(), "handlers", [handler, logging.NullHandler()])
    register_provider_secret(None)
    register_provider_secret("opaque-private-key")
    register_provider_secret("opaque-private-key")
    record = logging.LogRecord("test", logging.ERROR, "", 0, "opaque-private-key", (), None)
    assert "opaque-private-key" not in formatter.format(record)
    assert formatter.secrets == ("old-key", "opaque-private-key")


@pytest.mark.asyncio
async def test_container_legacy_model_and_shared_guard_come_from_saved_policy(tmp_path):
    from klipperai_agent.bootstrap.container import build_container

    settings = Settings(
        data_dir=tmp_path / "data",
        printer_data_root=tmp_path / "printer",
        provider_storage_dir=tmp_path / "private",
        agent_enabled=False,
        collect_host_logs=False,
        collect_systemd_diagnostics=False,
    )
    manager, _ = provider_management(settings)
    policy = ProviderPolicy(provider="openai", legacy=ModelProfile(model="legacy-model"))
    manager.store.save(0, policy, "stored-key")
    container = build_container(settings)
    try:
        assert container.chat_service.provider_model == "legacy-model"
        assert container.chat_service.agent_workflow is None
        context = container.chat_service.workflow_context
        assert context.llm._client._guard is context.config_llm._client._guard
        assert context.llm._client._guard is context.intent_router._client._guard
        assert context.llm._client._profile.model == "legacy-model"
        assert context.llm._client._api_key == "stored-key"
    finally:
        await container.aclose()
