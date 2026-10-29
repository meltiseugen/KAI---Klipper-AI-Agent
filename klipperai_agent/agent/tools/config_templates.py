"""Read-only template scaffolds for the model to inspect and refine."""

from typing import Any

from pydantic import Field, StrictStr

from klipperai_agent.agent.tools.base import Tool, ToolArguments, ToolContext
from klipperai_agent.config.models import ConfigRequestTarget
from klipperai_agent.config.requests import ConfigPromptPayload
from klipperai_agent.config.templates.catalog import ProposalCatalog
from klipperai_agent.domain.proposals import ConfigFeature
from klipperai_agent.profile.models import PrinterProfile


class TemplateArguments(ToolArguments):
    feature: ConfigFeature
    request: StrictStr = Field(min_length=1, max_length=4000)


class ConfigTemplateTool(Tool[TemplateArguments]):
    name = "get_config_template"
    label = "Read configuration template guidance"
    description = (
        "Get a deterministic draft scaffold using active config and saved profile evidence. "
        "Supply the requested feature and only user-supplied parameters. Unknown calibration "
        "and hardware values remain placeholders. Inspect and refine it before answering. "
        "This does not execute, validate firmware, or write any printer configuration."
    )
    arguments_type = TemplateArguments

    async def execute(self, arguments: TemplateArguments, context: ToolContext) -> dict[str, Any]:
        snapshot = await context.config()
        if not snapshot.documents:
            return {"error": "Active configuration is unavailable; collect it before drafting."}
        proposal = ProposalCatalog().build(
            ConfigPromptPayload(
                user_message=arguments.request,
                snapshot=snapshot,
                target=ConfigRequestTarget(arguments.feature, "Model-requested template guidance"),
                profile=PrinterProfile.from_state(context.services.profile.to_summary()),
            )
        )
        return {
            "template": proposal.model_dump(),
            "config_revision": snapshot.revision(),
            "context_notes": "Template guidance for the agent, not a verified final proposal. Unknown values require evidence and manual review.",
        }
