from __future__ import annotations

from types import SimpleNamespace

import klipperai_agent.__main__ as main_module


def test_main_configures_and_runs_uvicorn(monkeypatch) -> None:
    calls = {}
    settings = SimpleNamespace(
        host="127.0.0.1",
        port=8811,
        root_path="/klippyai",
        moonraker_url="http://moonraker",
        enable_write_actions=False,
        ensure_directories=lambda: calls.update(ensured=True),
    )
    monkeypatch.setattr(main_module, "get_settings", lambda: settings)
    monkeypatch.setattr(
        main_module, "configure_runtime_logging", lambda _settings: "/tmp/agent.log"
    )
    monkeypatch.setattr(
        main_module.uvicorn, "run", lambda *args, **kwargs: calls.update(args=args, kwargs=kwargs)
    )

    main_module.main()
    assert calls["ensured"] is True
    assert calls["args"] == ("klipperai_agent.web.app:create_app",)
    assert calls["kwargs"]["factory"] is True
    assert calls["kwargs"]["log_config"] is None


def test_legacy_commands_call_current_entrypoints(monkeypatch) -> None:
    from klipperai_agent.cli import legacy

    calls = []
    monkeypatch.setattr(legacy, "main", lambda: calls.append("agent"))
    monkeypatch.setattr(legacy, "detect_profile", lambda: calls.append("detect"))
    legacy.agent_main()
    legacy.detect_main()
    assert calls == ["agent", "detect"]
