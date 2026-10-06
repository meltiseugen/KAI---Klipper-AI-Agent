from __future__ import annotations

from klipperai_agent.config.lookup import build_config_lookup_response
from klipperai_agent.config.requests import ConfigPromptPayload
from klipperai_agent.config.templates.catalog import ProposalCatalog
from klipperai_agent.config.templates.guidance import ProposalGuidance
from klipperai_agent.providers.models import ConfigAssistantOutput


class StubConfigAssistantProvider:
    name = "stub"

    def __init__(self) -> None:
        self._catalog = ProposalCatalog()

    async def propose(self, payload: ConfigPromptPayload) -> ConfigAssistantOutput:
        if payload.target.intent in {"locate", "explain"}:
            response_text, next_actions = build_config_lookup_response(
                payload.snapshot,
                payload.target,
                include_content=payload.target.intent == "explain",
            )
            return ConfigAssistantOutput(
                summary=response_text,
                proposals=[],
                next_actions=next_actions,
                follow_up_questions=[],
            )

        proposal = self._catalog.build(payload)
        profile_summary = payload.profile.summary_label()
        summary = f"Generated a first-pass {proposal.feature} config proposal based on the current request and collected printer config."
        if profile_summary:
            summary += f" Detected printer profile: {profile_summary}."
        return ConfigAssistantOutput(
            summary=summary,
            proposals=[proposal],
            next_actions=ProposalGuidance._build_next_actions(proposal.feature),
            follow_up_questions=ProposalGuidance._build_follow_up_questions(proposal.feature),
        )
