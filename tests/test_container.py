from __future__ import annotations

from types import SimpleNamespace

import klipperai_agent.bootstrap.container as container_module
from klipperai_agent.runtime.settings import Settings


class _Moonraker:
    def __init__(self, url: str) -> None:
        self.url = url
        self.closed = False

    async def aclose(self) -> None:
        self.closed = True


def test_build_container_wires_optional_collectors(monkeypatch, tmp_path) -> None:
    created: dict[str, object] = {}

    def record(name):
        def factory(*args, **kwargs):
            value = SimpleNamespace(name=name, args=args, kwargs=kwargs)
            created[name] = value
            return value

        return factory

    monkeypatch.setattr(container_module, "MoonrakerClient", _Moonraker)
    for name in (
        "HostLogCollector",
        "SystemCommandRunner",
        "HostSystemCollector",
        "DiagnosticsCollector",
        "RuleEngine",
        "ConfigCollector",
        "InMemorySessionStore",
        "ChatService",
    ):
        monkeypatch.setattr(container_module, name, record(name))
    monkeypatch.setattr(
        container_module,
        "build_diagnosis_provider",
        lambda _settings: SimpleNamespace(name="diagnosis"),
    )
    monkeypatch.setattr(
        container_module, "build_config_provider", lambda _settings: SimpleNamespace(name="config")
    )
    monkeypatch.setattr(
        container_module, "build_intent_router", lambda _settings: SimpleNamespace(name="intent")
    )
    monkeypatch.setattr(
        container_module, "build_profile_from_settings", lambda _settings: "profile"
    )
    monkeypatch.setattr(container_module, "build_diagnosis_graph", lambda: "diagnosis")
    monkeypatch.setattr(container_module, "build_config_graph", lambda: "config")

    settings = Settings(
        data_dir=tmp_path / "data",
        checkpoint_db=tmp_path / "data" / "db.sqlite",
        printer_data_root=tmp_path / "printer_data",
        collect_host_logs=True,
        collect_systemd_diagnostics=True,
        root_path="/klippyai/",
    )
    result = container_module.build_container(settings)

    assert result.settings is settings
    assert result.moonraker.url == settings.moonraker_url
    assert created["HostLogCollector"].kwargs["excluded_logs"] == []
    assert created["HostSystemCollector"].kwargs["runner"].name == "SystemCommandRunner"
    assert created["ChatService"].kwargs["root_path"] == "/klippyai"
    awaitable = result.aclose()
    import asyncio

    asyncio.run(awaitable)
    assert result.moonraker.closed is True


def test_build_container_disables_optional_collectors(monkeypatch, tmp_path) -> None:
    captured = {}
    monkeypatch.setattr(container_module, "MoonrakerClient", _Moonraker)
    monkeypatch.setattr(
        container_module,
        "DiagnosticsCollector",
        lambda *args, **kwargs: captured.update(kwargs) or object(),
    )
    monkeypatch.setattr(container_module, "RuleEngine", lambda: object())
    monkeypatch.setattr(
        container_module, "build_diagnosis_provider", lambda _settings: SimpleNamespace(name="stub")
    )
    monkeypatch.setattr(container_module, "build_config_provider", lambda _settings: object())
    monkeypatch.setattr(container_module, "build_intent_router", lambda _settings: object())
    monkeypatch.setattr(container_module, "ConfigCollector", lambda *args, **kwargs: object())
    monkeypatch.setattr(container_module, "build_profile_from_settings", lambda _settings: object())
    monkeypatch.setattr(container_module, "build_diagnosis_graph", lambda: object())
    monkeypatch.setattr(container_module, "build_config_graph", lambda: object())
    monkeypatch.setattr(container_module, "InMemorySessionStore", lambda _ttl: object())
    monkeypatch.setattr(container_module, "ChatService", lambda **_kwargs: object())

    settings = Settings(
        data_dir=tmp_path / "data",
        checkpoint_db=tmp_path / "data" / "db.sqlite",
        printer_data_root=tmp_path / "printer_data",
        collect_host_logs=False,
        collect_systemd_diagnostics=False,
    )
    container_module.build_container(settings)
    assert captured == {"host_logs": None, "host_system": None}
