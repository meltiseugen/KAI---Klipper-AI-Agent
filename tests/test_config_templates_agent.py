from dataclasses import replace

import pytest

from klipperai_agent.agent.models import AgentLimits
from klipperai_agent.agent.tools.config_templates import ConfigTemplateTool, TemplateArguments
from klipperai_agent.agent.workflow import AgentWorkflow
from tests.test_agent import ScriptedModel, answer, call
from tests.test_agent import tool_context as tool_context


@pytest.mark.asyncio
async def test_template_guidance_is_a_validated_read_only_observation_for_the_model(tool_context):
    tool = ConfigTemplateTool()
    for values in (
        {"feature": "shell", "request": "run a command"},
        {"feature": "probe", "request": "x" * 4001},
        {"feature": "probe", "request": "configure", "path": "../../secret"},
    ):
        with pytest.raises(ValueError):
            TemplateArguments.parse_obj(values)
    result = await tool.execute(
        TemplateArguments(feature="probe", request="Create a probe configuration"), tool_context
    )
    assert "<" in result["template"]["config"]
    assert result["config_revision"] == (await tool_context.config()).revision()
    model = ScriptedModel(
        call(
            "get_config_template", {"feature": "probe", "request": "Create a probe configuration"}
        ),
        answer(),
    )
    result = await AgentWorkflow(model, tool_context.moonraker, AgentLimits()).ainvoke(
        {"user_message": "Create a probe configuration"}, context=tool_context.services
    )
    assert result["agent_status"] == "completed"
    assert "Template guidance for the agent" in str(model.conversations[-1])
    tool_context.snapshots[False] = replace(await tool_context.config(), documents=[])
    assert "error" in await tool.execute(
        TemplateArguments(feature="probe", request="configure"), tool_context
    )
