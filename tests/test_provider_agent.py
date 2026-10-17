from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from klipperai_agent.agent.models import AgentLimits
from klipperai_agent.agent.workflow import AgentWorkflow
from klipperai_agent.contracts.api import ChatRequest
from klipperai_agent.domain.provider_settings import ProviderLimitError
from tests.test_agent_integration import agent_service as agent_service


@pytest.mark.asyncio
async def test_agent_budget_stop_is_a_visible_limited_outcome(agent_service):
    model = SimpleNamespace(
        respond=AsyncMock(side_effect=ProviderLimitError("Daily provider usage limit reached."))
    )
    agent_service.agent_workflow = AgentWorkflow(model, SimpleNamespace(), AgentLimits())
    session = await agent_service.create_ui_session()
    result = await agent_service.chat(
        ChatRequest(session_id=session.session_id, message="What firmware?")
    )
    assert result.agent_status == "limited"
    assert "Daily provider usage limit" in result.response
    model.respond.assert_awaited_once()
