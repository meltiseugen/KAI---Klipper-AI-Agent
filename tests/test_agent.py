from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from klipperai_agent.agent.models import AgentLimits, ModelTurn, SearchResult, ToolCall
from klipperai_agent.agent.registry import ToolRegistry
from klipperai_agent.agent.runner import AgentRunner
from klipperai_agent.agent.tools.base import Tool, ToolArguments, ToolContext
from klipperai_agent.agent.workflow import AgentWorkflow
from klipperai_agent.config.collector import ConfigCollector
from klipperai_agent.contracts.api import ArtifactInput, SourceCitation
from klipperai_agent.diagnostics.models import DiagnosticsSnapshot
from klipperai_agent.diagnostics.rules import RuleEngine
from klipperai_agent.domain.investigation import InvestigationRequest
from klipperai_agent.profile.models import PrinterProfile


class ScriptedModel:
    def __init__(self, *turns):
        self.turns = list(turns)
        self.conversations = []

    async def respond(self, conversation, tools):
        self.conversations.append(json.loads(json.dumps(conversation)))
        turn = self.turns.pop(0)
        if isinstance(turn, Exception):
            raise turn
        return turn


def call(name, arguments=None, identifier="call-1"):
    item = {
        "type": "function_call",
        "name": name,
        "arguments": json.dumps(arguments or {}),
        "call_id": identifier,
    }
    return ModelTurn(output=[item], calls=[ToolCall(identifier, name, item["arguments"])])


def answer(text="Evidence-backed answer"):
    content = json.dumps({"response": text, "next_actions": ["Review the evidence"]})
    return ModelTurn(
        output=[
            {
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": content}],
            }
        ],
        text=content,
    )


@pytest.fixture
def tool_context(tmp_path):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "printer.cfg").write_text(
        "[printer]\nkinematics: corexy\n[extruder]\nstep_pin: PA1\n"
    )
    (config_dir / "inactive.cfg").write_text("[gcode_macro OLD]\ngcode: G28\n")
    artifacts = [
        ArtifactInput(
            kind="klippy_log", label="klippy.log", content="MCU 'mcu' shutdown: Timer too close"
        )
    ]
    services = SimpleNamespace(
        config_collector=ConfigCollector(tmp_path),
        profile=PrinterProfile(firmware_flavor="Kalico"),
        collector=SimpleNamespace(
            collect=AsyncMock(return_value=DiagnosticsSnapshot(True, {}, artifacts))
        ),
        rules=RuleEngine(),
    )
    moonraker = SimpleNamespace(
        get_printer_info=AsyncMock(return_value={"state": "ready"}),
        list_printer_objects=AsyncMock(return_value=["toolhead", "extruder", "untrusted_name"]),
        query_printer_objects=AsyncMock(return_value={"extruder": {"temperature": 22}}),
    )
    return ToolContext(services, moonraker, artifacts)


@pytest.mark.asyncio
async def test_agent_observes_tools_and_follows_up_with_config_and_web_sources(tool_context):
    model = ScriptedModel(
        call("get_printer_profile"),
        call("inspect_config", identifier="2"),
        call("inspect_config", {"section": "extruder"}, "3"),
        call("read_config_file", {"path": "printer.cfg", "start_line": 3}, "4"),
        call("get_printer_status", identifier="5"),
        call("collect_diagnostics", {"include_system": True}, "6"),
        call("search_web", {"query": "Klipper Timer too close"}, "7"),
        answer(),
    )
    search = SimpleNamespace(
        search=AsyncMock(
            return_value=SearchResult(
                "Official troubleshooting guidance",
                [
                    SourceCitation(
                        label="Klipper FAQ",
                        path="https://www.klipper3d.org/FAQ.html",
                        url="https://www.klipper3d.org/FAQ.html",
                    )
                ],
            )
        )
    )
    workflow = AgentWorkflow(model, tool_context.moonraker, AgentLimits(), search)
    events = []

    async def emit(event):
        events.append(event)

    state = {
        "user_message": "Why did it fail?",
        "on_event": emit,
        "artifacts": [a.model_dump() for a in tool_context.artifacts],
    }
    result = await workflow.ainvoke(state, context=tool_context.services)
    assert workflow.web_search_enabled
    assert result["agent_status"] == "completed"
    assert result["response_text"] == "Evidence-backed answer"
    assert result["findings"] and result["moonraker_reachable"]
    assert any(source["line_number"] == 3 for source in result["source_citations"])
    assert any(source["url"] for source in result["source_citations"])
    assert len(events) == 14
    assert "PA1" in json.dumps(model.conversations[-1])
    assert "Official troubleshooting guidance" in json.dumps(model.conversations[-1])
    assert events[0].kind == "tool_started" and events[-1].kind == "tool_completed"
    tool_context.moonraker.query_printer_objects.assert_awaited_once_with(
        {"toolhead": None, "extruder": None}
    )


@pytest.mark.asyncio
async def test_tools_do_not_read_unknown_paths_and_recover_from_missing_evidence(tool_context):
    model = ScriptedModel(
        call("read_config_file", {"path": "../../secret.env"}),
        call("inspect_config", {"section": "gcode_macro OLD", "include_unincluded": True}, "2"),
        call("search_web", {"query": "Klipper"}, "3"),
        answer("Some evidence was unavailable."),
    )
    workflow = AgentWorkflow(model, tool_context.moonraker, AgentLimits())
    result = await workflow.ainvoke({"user_message": "Find OLD"}, context=tool_context.services)
    assert not workflow.web_search_enabled
    assert result["agent_status"] == "completed"
    assert result["source_citations"][0]["path"] == "inactive.cfg"
    assert sum(event["kind"] == "tool_error" for event in result["agent_events"]) == 2
    assert "not in the collected" in json.dumps(model.conversations[1])
    assert "may not be active" in json.dumps(model.conversations[-1])


class CountingTool(Tool[ToolArguments]):
    name = "count"
    description = "Test read-only operation"
    label = "Count"
    arguments_type = ToolArguments

    def __init__(self, result=None, *, error=False, delay=0):
        self.calls = 0
        self.result = result or {"value": 1}
        self.error = error
        self.delay = delay

    async def execute(self, arguments, context):
        self.calls += 1
        if self.error:
            raise RuntimeError("unavailable")
        if self.delay:
            await asyncio.sleep(self.delay)
        return self.result


@pytest.mark.asyncio
async def test_registry_validates_caches_bounds_and_handles_failures(tool_context):
    tool = CountingTool()
    registry = ToolRegistry([tool], AgentLimits())
    assert registry.definitions()[0]["parameters"]["additionalProperties"] is False
    for args in ("[]", "{", '{"extra": 1}', "x" * 6001):
        assert "error" in await registry.execute(ToolCall("1", "count", args), tool_context)
    first = await registry.execute(ToolCall("1", "count", "{}"), tool_context)
    assert await registry.execute(ToolCall("2", "count", "{}"), tool_context) == first
    assert tool.calls == 1
    with pytest.raises(ValueError, match="Duplicate"):
        ToolRegistry([tool, tool], AgentLimits())
    failing = CountingTool(error=True)
    registry = ToolRegistry([failing], AgentLimits())
    assert "error" in await registry.execute(ToolCall("1", "count", "{}"), tool_context)
    assert "error" in await registry.execute(ToolCall("2", "count", "{}"), tool_context)
    assert failing.calls == 2
    timeout = ToolRegistry([CountingTool(delay=1)], AgentLimits(tool_timeout_seconds=0.001))
    assert (
        "timed out" in (await timeout.execute(ToolCall("1", "count", "{}"), tool_context))["error"]
    )
    bounded = ToolRegistry([CountingTool({"text": "x" * 100})], AgentLimits(max_result_chars=20))
    result = await bounded.execute(ToolCall("1", "count", "{}"), tool_context)
    assert result["truncated"] and len(result["excerpt"]) == 20


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "limit,turns,expected",
    [
        (AgentLimits(max_steps=1), [call("count")], "step limit"),
        (
            AgentLimits(max_tool_calls=1),
            [call("count"), call("count", identifier="2")],
            "tool-call limit",
        ),
        (AgentLimits(max_context_chars=1), [], "context limit"),
        (AgentLimits(), [RuntimeError("bad provider")], "model could not complete"),
        (AgentLimits(), [call("count"), call("count")], "model could not complete"),
    ],
)
async def test_agent_stops_on_limits_and_protocol_errors(tool_context, limit, turns, expected):
    runner = AgentRunner(ScriptedModel(*turns), limit)
    result = await runner.run(
        InvestigationRequest(user_message="help"),
        tool_context,
        ToolRegistry([CountingTool()], limit),
    )
    assert expected in result.response_text
    assert result.agent_status in {"limited", "error"}


@pytest.mark.asyncio
async def test_agent_repairs_final_json_times_out_and_propagates_cancellation(tool_context):
    runner = AgentRunner(
        ScriptedModel(ModelTurn([], text="malformed"), answer("   "), answer()), AgentLimits()
    )
    result = await runner.run(
        InvestigationRequest(user_message="help"), tool_context, ToolRegistry([], AgentLimits())
    )
    assert result.agent_status == "completed"

    class SlowModel:
        async def respond(self, *args):
            await asyncio.sleep(5)

    runner = AgentRunner(SlowModel(), AgentLimits(run_timeout_seconds=0.001))
    assert (
        await runner.run(
            InvestigationRequest(user_message="help"), tool_context, ToolRegistry([], AgentLimits())
        )
    ).agent_status == "limited"
    task = asyncio.create_task(
        AgentRunner(SlowModel(), AgentLimits()).run(
            InvestigationRequest(user_message="help"),
            tool_context,
            ToolRegistry([], AgentLimits()),
        )
    )
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
async def test_runs_have_isolated_evidence_and_empty_object_status_is_valid(tool_context):
    tool_context.moonraker.list_printer_objects.return_value = []
    model = ScriptedModel(call("get_printer_status"), answer(), answer("Unrelated question"))
    workflow = AgentWorkflow(model, tool_context.moonraker, AgentLimits())
    first = await workflow.ainvoke({"user_message": "status"}, context=tool_context.services)
    second = await workflow.ainvoke({"user_message": "general"}, context=tool_context.services)
    assert first["moonraker_reachable"] and not second["moonraker_reachable"]
    assert not second["agent_events"] and not second["source_citations"]
    tool_context.moonraker.query_printer_objects.assert_not_called()


@pytest.mark.asyncio
async def test_inactive_lookup_keeps_separate_active_revision(tool_context):
    inactive = await tool_context.config(True)
    active = await tool_context.config(False)
    assert len(inactive.documents) > len(active.documents)
    assert inactive.revision() != active.revision()


@pytest.mark.asyncio
async def test_final_answer_after_call_budget_and_out_of_range_config(tool_context):
    model = ScriptedModel(
        call("read_config_file", {"path": "printer.cfg", "start_line": 900}), answer()
    )
    result = await AgentWorkflow(
        model, tool_context.moonraker, AgentLimits(max_tool_calls=1)
    ).ainvoke(
        {"user_message": "Read config"},
        context=tool_context.services,
    )
    assert result["agent_status"] == "completed"
    assert not result["source_citations"]
    assert result["agent_events"][1]["kind"] == "tool_error"
    assert "outside the collected excerpt" in json.dumps(model.conversations[-1])
    assert "tool budget is exhausted" in json.dumps(model.conversations[-1])
