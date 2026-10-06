from __future__ import annotations

from klipperai_agent.application.intent import (
    ChatIntentOutput,
    classify_deterministic_intent,
)
from klipperai_agent.diagnostics.requests import DiagnosisPromptPayload
from klipperai_agent.providers.models import DiagnosisLLMOutput


class StubIntentRouterProvider:
    name = "stub"

    async def classify(self, message: str) -> ChatIntentOutput:
        return classify_deterministic_intent(message)


class StubDiagnosisProvider:
    name = "stub"

    async def analyze(self, payload: DiagnosisPromptPayload) -> DiagnosisLLMOutput:
        profile_summary = payload.profile.summary_label()
        if payload.findings:
            recommended_actions = [finding.proposed_fix for finding in payload.findings[:3]]
            likely_causes = [finding.summary for finding in payload.findings[:3]]
            summary = payload.findings[0].summary
            if profile_summary:
                summary += f" Detected printer profile: {profile_summary}."
        else:
            recommended_actions = [
                "Paste relevant klippy.log, moonraker.log, or config excerpts.",
                "Ask a more specific question about the failure mode you are seeing.",
            ]
            likely_causes = [
                "Insufficient context in the current request.",
            ]
            summary = (
                "No deterministic issue matched yet, and no external LLM provider is configured."
            )
            if profile_summary:
                summary += f" Current detected profile: {profile_summary}."

        return DiagnosisLLMOutput(
            summary=summary,
            likely_causes=likely_causes,
            recommended_actions=recommended_actions,
            follow_up_questions=[
                "What changed just before the issue started?",
                "Can you share the exact log lines around the first error?",
            ],
        )
