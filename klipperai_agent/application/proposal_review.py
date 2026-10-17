from __future__ import annotations

import asyncio
from dataclasses import replace

from klipperai_agent.agent.ports import ConfigReader, KnowledgeReader
from klipperai_agent.config.models import ConfigReadError, ConfigSnapshot
from klipperai_agent.config.review import ProposalReviewer
from klipperai_agent.domain.investigation import InvestigationResult
from klipperai_agent.knowledge.review import review_fan_hardware


class ProposalReviewService:
    def __init__(self, configs: ConfigReader, knowledge: KnowledgeReader | None = None):
        self._configs = configs
        self._reviewer = ProposalReviewer()
        self._knowledge = knowledge

    async def review(self, result: InvestigationResult, *, revalidate: bool = False) -> None:
        if not result.config_proposals:
            return
        snapshot = await asyncio.to_thread(self._configs.collect_with_options)
        expected = next(
            (item.config_revision for item in reversed(result.evidence) if item.config_revision),
            None,
        )
        result.config_proposals = [
            self._reviewer.review(
                proposal,
                snapshot,
                previous=proposal.review if revalidate else None,
                expected_revision=expected,
            )
            for proposal in result.config_proposals
        ]
        if self._knowledge is not None:
            setup, docs, changed = await self._knowledge.read()
            hardware_snapshot = await asyncio.to_thread(self._hardware_snapshot, snapshot)
            for proposal in result.config_proposals:
                errors = review_fan_hardware(proposal, hardware_snapshot, setup, docs, changed)
                if proposal.review and errors:
                    proposal.review.errors.extend(errors)
                    if proposal.review.status != "stale":
                        proposal.review.status = "needs_information"

    def _hardware_snapshot(self, snapshot: ConfigSnapshot) -> ConfigSnapshot:
        documents = []
        size = 0
        try:
            for document in snapshot.documents:
                full = (
                    self._configs.read_collected_document(document)
                    if document.truncated
                    else document
                )
                size += len(full.content)
                if size > 2_000_000:
                    raise ConfigReadError("Configuration exceeds hardware review budget.")
                documents.append(full)
        except (OSError, ConfigReadError):
            return replace(
                snapshot,
                notes=[
                    *snapshot.notes,
                    "Full configuration could not be read for hardware review.",
                ],
            )
        return replace(snapshot, documents=documents)
