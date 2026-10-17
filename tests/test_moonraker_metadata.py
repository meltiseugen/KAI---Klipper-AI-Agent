import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import ValidationError

from klipperai_agent.agent.models import AgentLimits
from klipperai_agent.agent.tools.file_metadata import FileMetadataArguments, FileMetadataTool
from klipperai_agent.agent.workflow import AgentWorkflow
from klipperai_agent.infrastructure.moonraker import MoonrakerError
from tests.test_agent import ScriptedModel, answer, call
from tests.test_agent import tool_context as tool_context
from tests.test_moonraker import _client


@pytest.mark.asyncio
async def test_metadata_http_is_read_only_escaped_allowlisted_and_bounded():
    def handler(request):
        assert request.method == "GET"
        assert request.url.path == "/server/files/metadata"
        assert dict(request.url.params) == {"filename": "parts/my #part&x.gcode"}
        return httpx.Response(
            200,
            json={
                "result": {
                    "size": 123,
                    "estimated_time": 500,
                    "slicer": "x" * 1000,
                    "filament_name": "api_key=sk-private-value",
                    "layer_height": {"nested": 10},
                    "thumbnails": [{"relative_path": "private.png"}],
                    "gcode_start_byte": 500,
                }
            },
        )

    client = _client(handler)
    try:
        data = await client.get_file_metadata("parts/my #part&x.gcode")
        assert data["estimated_time"] == 500 and data["size"] == 123
        assert len(data["slicer"]) == 512 and data["layer_height"] is None
        assert "sk-private-value" not in json.dumps(data)
        assert "thumbnails" not in data and "gcode_start_byte" not in data
        with pytest.raises(ValueError):
            await client.get_file_metadata("../config/printer.cfg")
        for payload in ([], {"error": "private path"}):
            client._request = AsyncMock(return_value=payload)
            with pytest.raises(MoonrakerError):
                await client.get_file_metadata("part.gcode")
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_metadata_arguments_current_file_and_missing_evidence(tool_context):
    reader = SimpleNamespace(get_file_metadata=AsyncMock(return_value={"estimated_time": 600}))
    tool = FileMetadataTool(reader)
    for arguments in (
        {"filename": "../printer.cfg"},
        {"filename": 4},
        {"filename": "a", "start": True},
    ):
        with pytest.raises(ValidationError):
            FileMetadataArguments(**arguments)
    assert FileMetadataArguments(filename=None).filename is None
    assert "error" in await tool.execute(FileMetadataArguments(), tool_context)
    reader.get_file_metadata.assert_not_awaited()
    tool_context.moonraker.query_printer_objects.return_value = {
        "print_stats": {"filename": "part.gcode"}
    }
    result = await tool.execute(FileMetadataArguments(), tool_context)
    assert result["filename"] == "part.gcode" and result["observed_at"]
    assert result["metadata"] == {"estimated_time": 600}
    assert tool_context.citations[-1].path == "gcodes/part.gcode"
    assert tool_context.moonraker_reachable
    reader.get_file_metadata.return_value = {}
    assert "error" in await tool.execute(
        FileMetadataArguments(filename="missing.gcode"), tool_context
    )
    tool_context.moonraker.query_printer_objects.return_value = {
        "print_stats": {"filename": "../secret"}
    }
    with pytest.raises(ValueError):
        await tool.execute(FileMetadataArguments(), tool_context)


@pytest.mark.asyncio
async def test_agent_observes_metadata_then_uses_it_in_answer(tool_context):
    reader = SimpleNamespace(
        get_file_metadata=AsyncMock(return_value={"slicer": "OrcaSlicer", "estimated_time": 600})
    )
    model = ScriptedModel(
        call("get_gcode_metadata", {"filename": "parts/test.gcode"}),
        answer("The slicer estimates ten minutes."),
    )
    workflow = AgentWorkflow(model, tool_context.moonraker, AgentLimits(), file_metadata=reader)
    result = await workflow.ainvoke(
        {"user_message": "What is the slicer estimate?"}, context=tool_context.services
    )
    assert result["agent_status"] == "completed"
    assert '"estimated_time": 600' in str(model.conversations[-1])
    assert any(item["path"] == "gcodes/parts/test.gcode" for item in result["source_citations"])
    reader.get_file_metadata.assert_awaited_once_with("parts/test.gcode")
