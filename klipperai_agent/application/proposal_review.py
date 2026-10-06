from __future__ import annotations

import asyncio

from klipperai_agent.agent.ports import ConfigReader
from klipperai_agent.config.review import ProposalReviewer
from klipperai_agent.domain.investigation import InvestigationResult


class ProposalReviewService:
    def __init__(self, configs: ConfigReader):
        self._configs = configs
        self._reviewer = ProposalReviewer()

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
