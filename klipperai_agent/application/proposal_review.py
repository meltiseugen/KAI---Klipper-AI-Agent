from __future__ import annotations

import asyncio
from dataclasses import replace

from klipperai_agent.agent.ports import ConfigReader, KnowledgeReader, PrinterReader, SavedProfile
from klipperai_agent.application.review_firmware import read_review_firmware
from klipperai_agent.config.models import ConfigReadError, ConfigSnapshot
from klipperai_agent.config.review import ProposalReviewer
from klipperai_agent.domain.investigation import InvestigationResult
from klipperai_agent.knowledge.review import review_fan_hardware


class ProposalReviewService:
    def __init__(
        self,
        configs: ConfigReader,
        knowledge: KnowledgeReader | None = None,
        *,
        printer: PrinterReader | None = None,
        profile: SavedProfile | None = None,
    ):
        self._configs = configs
        self._reviewer = ProposalReviewer()
        self._knowledge = knowledge
        self._printer = printer
        self._profile = profile

    async def review(self, result: InvestigationResult, *, revalidate: bool = False) -> None:
        if not result.config_proposals:
            return
        snapshot = await asyncio.to_thread(self._configs.collect_with_options)
        targets = {proposal.target_file.replace("\\", "/") for proposal in result.config_proposals}
        if snapshot.root_file:
            targets.add(snapshot.root_file)
        snapshot = await asyncio.to_thread(self._hardware_snapshot, snapshot, targets)
        inventory = await asyncio.to_thread(
            self._configs.collect_with_options, include_unincluded_configs=True
        )
        inventory = await asyncio.to_thread(self._hardware_snapshot, inventory, targets)
        firmware = await read_review_firmware(self._printer, self._profile)
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
                firmware=firmware,
                inventory=inventory,
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
                    proposal.review.file_patches = []
        # Independently drafted patches to the same file may disagree. Never present
        # those as a coherent patch set; ask for one consolidated draft.
        diffs: dict[str, set[str]] = {}
        for proposal in result.config_proposals:
            if proposal.review:
                for patch in proposal.review.file_patches:
                    diffs.setdefault(patch.target_file, set()).add(patch.diff)
        for proposal in result.config_proposals:
            review = proposal.review
            if review and any(len(diffs[p.target_file]) > 1 for p in review.file_patches):
                review.file_patches = []
                review.errors.append(
                    "Multiple proposals change the same file differently. Request a consolidated proposal before editing."
                )
                review.status = "needs_information"

    def _hardware_snapshot(
        self, snapshot: ConfigSnapshot, paths: set[str] | None = None
    ) -> ConfigSnapshot:
        documents = []
        size = 0
        try:
            for document in snapshot.documents:
                full = (
                    self._configs.read_collected_document(document)
                    if document.truncated and (paths is None or document.path in paths)
                    else document
                )
                size += len(full.content)
                if size > 2_000_000:
                    raise ConfigReadError("Configuration exceeds the review read budget.")
                documents.append(full)
        except (OSError, ConfigReadError):
            return replace(
                snapshot,
                notes=[
                    *snapshot.notes,
                    "Full configuration could not be read for review.",
                ],
            )
        return replace(snapshot, documents=documents)
