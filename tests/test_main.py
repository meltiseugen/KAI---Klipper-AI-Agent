from __future__ import annotations

from types import SimpleNamespace

import kai_agent.__main__ as main_module


def test_main_configures_and_runs_uvicorn(monkeypatch) -> None:
    calls = {}
    settings = SimpleNamespace(
        host="127.0.0.1",
        port=8811,
        root_path="/kai",
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

    monkeypatch.setattr(main_module.os, "umask", lambda value: calls.update(umask=value))
    main_module.main()
    assert calls["umask"] == 0o077
    assert calls["kwargs"]["access_log"] is False
    assert calls["kwargs"]["server_header"] is False
    assert calls["kwargs"]["forwarded_allow_ips"] == "127.0.0.1,::1"
    assert calls["ensured"] is True
    assert calls["args"] == ("kai_agent.web.app:create_app",)
    assert calls["kwargs"]["factory"] is True
    assert calls["kwargs"]["root_path"] == "/kai"
    assert calls["kwargs"]["log_config"] is None
