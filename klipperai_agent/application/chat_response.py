"""Bounded public response projection; stored observations retain their identities."""

from klipperai_agent.contracts.api import ChatResponse
from klipperai_agent.domain.artifacts import public_evidence_blocks
from klipperai_agent.domain.investigation import InvestigationResult


def chat_response(
    session_id: str, thread_id: str, provider: str, outcome: InvestigationResult
) -> ChatResponse:
    priority = {finding.evidence_ids[0] for finding in outcome.findings if finding.evidence_ids}
    blocks = public_evidence_blocks(
        sorted(outcome.evidence, key=lambda item: item.id not in priority)
    )
    return ChatResponse(
        session_id=session_id,
        thread_id=thread_id,
        provider=provider,
        model_usage=outcome.model_usage,
        mode=outcome.mode,
        context_included=outcome.context_included,
        response=outcome.response_text,
        workflow=outcome.workflow,
        answer_claims=outcome.answer_claims,
        missing_evidence=outcome.missing_evidence,
        hypotheses=outcome.hypotheses,
        findings=outcome.findings,
        next_actions=outcome.next_actions,
        config_proposals=outcome.config_proposals,
        patch_proposals=outcome.patch_proposals,
        source_citations=outcome.source_citations,
        moonraker_reachable=outcome.moonraker_reachable,
        agent_events=outcome.agent_events,
        agent_status=outcome.agent_status,
        memory_sources=outcome.memory_sources,
        evidence_blocks=blocks,
        evidence_blocks_omitted=max(0, len({item.id for item in outcome.evidence}) - len(blocks)),
    )
