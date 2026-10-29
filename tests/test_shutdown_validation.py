from __future__ import annotations

import json
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from klipperai_agent.runtime.settings import Settings
from tools import validate_shutdown as validation


def test_real_public_incidents_replay_with_provenance_and_conservative_causes():
    reports = validation.replay_cases()
    usb, can = reports
    assert all(report["fixture_replay"] == "passed" for report in reports)
    assert usb["incident"]["family"] == "communication"
    assert usb["assessments"][0]["cause"] == "Cause not established"
    assert can["incident"]["estimated_unix_time"] is None
    assert can["incident"]["statistics"]["counter_increases"]["mcu.bytes_invalid"] == 111
    assert any("packet ordering" in str(item["next_steps"]) for item in can["assessments"])
    assert len(can["provenance"]["original_lines"]) == 4


def test_real_replay_rejects_changed_excerpts_and_failed_expectations(tmp_path):
    cases = json.loads(validation.CASES.read_text())
    for case in cases:
        (tmp_path / case["log"]).write_bytes((validation.CASES.parent / case["log"]).read_bytes())
    manifest = tmp_path / "cases.json"
    cases[0]["expected_family"] = "wrong"
    manifest.write_text(json.dumps(cases))
    assert validation.replay_cases(manifest)[0]["fixture_replay"] == "failed"
    (tmp_path / cases[0]["log"]).write_text("changed")
    with pytest.raises(ValueError, match="provenance"):
        validation.replay_cases(manifest)


@pytest.mark.asyncio
async def test_validation_live_provider_is_explicit_and_answers_require_review(monkeypatch):
    client = SimpleNamespace(aclose=AsyncMock())
    model = SimpleNamespace(
        respond=AsyncMock(return_value=SimpleNamespace(text='{"response":"insufficient evidence"}'))
    )
    monkeypatch.setattr(
        validation,
        "get_settings",
        lambda: Settings(llm_provider="openai", openai_api_key="test-only"),
    )
    monkeypatch.setattr(
        validation,
        "provider_management",
        lambda settings: (SimpleNamespace(active_policy=None), object()),
    )
    monkeypatch.setattr(validation, "effective_settings", lambda settings, manager: settings)
    monkeypatch.setattr(validation, "ResponsesClient", lambda *args, **kwargs: client)
    monkeypatch.setattr(validation, "OpenAIAgentModel", lambda value: model)
    reports = validation.replay_cases()
    result = await validation.collect_provider_answers(reports)
    assert result["status"] == "answers_collected_pending_human_review"
    assert model.respond.await_count == 2
    assert reports[0]["provider_answer"]["response"] == "insufficient evidence"
    assert model.respond.call_args.args[1] == []
    client.aclose.assert_awaited_once()
    monkeypatch.setattr(validation, "get_settings", lambda: Settings())
    assert (await validation.collect_provider_answers(reports))["status"] == "unavailable"


@pytest.mark.asyncio
async def test_validation_cli_separates_disconnected_live_provider_and_printer(
    monkeypatch, tmp_path
):
    output = tmp_path / "validation.json"
    monkeypatch.setattr(sys, "argv", ["validate_shutdown", "--output", str(output)])
    assert await validation.main() == 0
    report = json.loads(output.read_text())
    assert report["live_provider"]["status"] == "not_run"
    assert report["live_printer"]["status"] == "not_run"
    monkeypatch.setattr(
        sys,
        "argv",
        ["validate_shutdown", "--live-provider", "--output", str(output)],
    )
    monkeypatch.setattr(
        validation, "collect_provider_answers", AsyncMock(return_value={"status": "unavailable"})
    )
    assert await validation.main() == 2
    assert json.loads(output.read_text())["live_provider"]["status"] == "unavailable"
