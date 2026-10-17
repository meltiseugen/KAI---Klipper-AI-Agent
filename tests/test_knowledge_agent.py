import json
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from klipperai_agent.agent.models import AgentLimits
from klipperai_agent.agent.tools.base import ToolArguments
from klipperai_agent.agent.tools.knowledge import (
    EddyArguments,
    EddyCalibrationTool,
    FanPortsArguments,
    FanPortsTool,
    PrinterKnowledgeTool,
    SearchKnowledgeArguments,
    SearchKnowledgeTool,
    complete_config,
)
from klipperai_agent.agent.workflow import AgentWorkflow
from klipperai_agent.application.proposal_review import ProposalReviewService
from klipperai_agent.config.collector import ConfigCollector
from klipperai_agent.config.models import ConfigReadError
from klipperai_agent.domain.investigation import Evidence, InvestigationResult
from tests.knowledge_helpers import documents, setup, snapshot
from tests.test_agent import ScriptedModel, answer, call
from tests.test_agent import tool_context as tool_context
from tests.test_knowledge import proposal


def reader(data=None):
    return SimpleNamespace(read=AsyncMock(return_value=(data or setup(), documents(), False)))


@pytest.mark.asyncio
async def test_agent_reads_knowledge_before_answer_and_follows_source_evidence(
    tool_context, tmp_path
):
    (tmp_path / "config/printer.cfg").write_text(
        snapshot("[fan]\npin: PA8").documents[0].content, encoding="utf-8"
    )
    model = ScriptedModel(
        call("inspect_fan_ports"),
        call("search_printer_knowledge", {"query": "Fan connector", "role": "mainboard"}, "2"),
        answer("FAN1 uses mcu:PB15; check the physical connector and supply voltage."),
    )
    workflow = AgentWorkflow(model, tool_context.moonraker, AgentLimits(), knowledge=reader())
    result = await workflow.ainvoke(
        {"user_message": "Add a fan", "mode": "chat"}, context=tool_context.services
    )
    initial = json.dumps(model.conversations[0])
    assert "Example Board A" in initial and "Fan0 is a 24V" in initial
    assert "mcu:PB15" in json.dumps(model.conversations[-1])
    assert result["agent_status"] == "completed"
    assert any("Example Board A" in item["label"] for item in result["source_citations"])
    assert any("cached" in item["label"] for item in result["source_citations"])
    assert any(item["source"] == "get_printer_knowledge" for item in result["context_included"])
    tool_context.services.collector.collect.assert_not_awaited()


@pytest.mark.asyncio
async def test_read_only_tools_identity_gaps_arguments_and_eddy_citations(tool_context):
    knowledge = reader()
    tool_context.snapshots[False] = snapshot(
        "[fan]\npin: PA8\n[probe_eddy_current btt]\nsensor_type: ldc1612"
    )
    result = await PrinterKnowledgeTool(knowledge).execute(ToolArguments(), tool_context)
    assert len(result["components"]) == 3
    search = await SearchKnowledgeTool(knowledge).execute(
        SearchKnowledgeArguments(query="calibration", role="probe"), tool_context
    )
    assert all(item["document_id"] in {"eddy-guide", "klipper-eddy"} for item in search["passages"])
    result = await EddyCalibrationTool(knowledge).execute(
        EddyArguments(symptom="bed calibration"), tool_context
    )
    assert result["configuration"] and any(
        item.path == "printer.cfg" for item in tool_context.citations
    )
    assert result["observed_firmware_version"] is None
    tool_context.moonraker.get_printer_info.return_value = {
        "software_version": "v0.13.0-500-newcommit"
    }
    live = await EddyCalibrationTool(knowledge).execute(
        EddyArguments(symptom="bed calibration"), tool_context
    )
    assert live["observed_firmware_version"] == "v0.13.0-500-newcommit"
    assert "differs from the saved version" in str(live["gaps"])
    tool_context.moonraker.get_printer_info.side_effect = ConnectionError("private host")
    offline = await EddyCalibrationTool(knowledge).execute(
        EddyArguments(symptom="bed calibration"), tool_context
    )
    assert offline["observed_firmware_version"] is None and "private host" not in str(offline)
    data = setup()
    data.components[1].mcu = "mcu"
    result = await FanPortsTool(reader(data)).execute(FanPortsArguments(), tool_context)
    assert "Multiple components" in str(result["gaps"])
    assert all(item["pin"] is None for item in result["ports"])
    data.components = []
    assert "error" in await FanPortsTool(reader(data)).execute(FanPortsArguments(), tool_context)
    for arguments, values in (
        (FanPortsArguments, {"role": "../probe"}),
        (FanPortsArguments, {"shell": "restart"}),
        (SearchKnowledgeArguments, {"query": "a"}),
        (SearchKnowledgeArguments, {"query": "fans", "url": "http://localhost"}),
        (EddyArguments, {"symptom": 12}),
    ):
        with pytest.raises(ValidationError):
            arguments(**values)


@pytest.mark.asyncio
async def test_full_config_expansion_and_failure_limits(tool_context, tmp_path):
    (tmp_path / "config/printer.cfg").write_text(
        snapshot("#" + "x" * 500 + "\n[fan]\npin: PA8").documents[0].content, encoding="utf-8"
    )
    tool_context.services.config_collector = ConfigCollector(tmp_path, max_chars_per_document=80)
    initial = await tool_context.config()
    full = await complete_config(tool_context)
    assert initial.documents[0].truncated and not full.documents[0].truncated
    assert full.revision() == initial.revision()
    assert (await FanPortsTool(reader()).execute(FanPortsArguments(), tool_context))["gaps"] == []
    tool_context.document = AsyncMock(return_value=None)
    with pytest.raises(ConfigReadError, match="unavailable"):
        await complete_config(tool_context)
    tool_context.document = AsyncMock(
        return_value=replace(full.documents[0], content="x" * 2_000_001)
    )
    with pytest.raises(ConfigReadError, match="budget"):
        await complete_config(tool_context)


@pytest.mark.asyncio
async def test_review_checks_hardware_after_static_review_and_preserves_staleness(tmp_path):
    configs = tmp_path / "config"
    configs.mkdir()
    (configs / "printer.cfg").write_text(
        snapshot("[fan]\npin: PA8").documents[0].content, encoding="utf-8"
    )
    collector = ConfigCollector(tmp_path)
    service = ProposalReviewService(collector, reader())
    result = InvestigationResult(config_proposals=[proposal("[fan_generic extra]\npin: PA8")])
    await service.review(result)
    assert result.config_proposals[0].review.status == "needs_information"
    assert "already used" in str(result.config_proposals[0].review.errors)
    result.evidence = [Evidence(source="old config", content="observed", config_revision="old")]
    await service.review(result)
    assert result.config_proposals[0].review.status == "stale"
    result.config_proposals = [proposal("[fan_generic extra]\npin: PB15")]
    result.evidence = []
    await service.review(result)
    assert result.config_proposals[0].review.status == "manual_review"
    collector._max_chars_per_document = 50
    observed = collector.collect()
    expanded = service._hardware_snapshot(observed)
    assert not expanded.documents[0].truncated
    collector.read_collected_document = lambda doc: replace(doc, content="x" * 2_000_001)
    assert "could not be read" in str(service._hardware_snapshot(observed).notes)
