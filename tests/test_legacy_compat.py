from __future__ import annotations

import os

from klipperai_agent.cli.legacy import export_legacy_environment


def test_legacy_environment_is_mapped_without_overriding_new_values(monkeypatch) -> None:
    monkeypatch.setenv("KLIPPYAI_CONFIG_FILE", "/legacy/klippyai.cfg")
    monkeypatch.setenv("KLIPPYAI_OPENAI_API_KEY", "legacy-key")
    monkeypatch.setenv("KLIPPERAI_OPENAI_API_KEY", "new-key")
    monkeypatch.delenv("KLIPPERAI_CONFIG_FILE", raising=False)

    export_legacy_environment()

    assert os.environ["KLIPPERAI_CONFIG_FILE"] == "/legacy/klippyai.cfg"
    assert os.environ["KLIPPERAI_OPENAI_API_KEY"] == "new-key"
