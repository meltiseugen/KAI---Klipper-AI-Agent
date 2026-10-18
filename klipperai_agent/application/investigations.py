"""Conversation history and relevant historical evidence for one configured printer."""

from __future__ import annotations

import asyncio
import re
from uuid import uuid4

from klipperai_agent.domain.investigation import (
    ConfirmedMemory,
    Evidence,
    Investigation,
    InvestigationResult,
    InvestigationTurn,
    PendingInvestigation,
)
from klipperai_agent.domain.messages import ChatHistoryMessage
from klipperai_agent.domain.repositories import InvestigationRepository


class InvestigationMemory:
    def __init__(
        self, repository: InvestigationRepository, printer_id: str, *, cross_chat: bool = True
    ):
        self._repository = repository
        self._printer_id = printer_id
        self._cross_chat = cross_chat

    async def confirmed(self) -> list[ConfirmedMemory]:
        return await asyncio.to_thread(self._repository.confirmed.list, self._printer_id)

    async def confirm(self, item: ConfirmedMemory, evidence_ids: list[str]) -> ConfirmedMemory:
        record = await self.get(item.investigation_id) if item.investigation_id else None
        if item.investigation_id and record is None:
            raise ValueError("Source investigation not found.")
        available = (
            {e.id: e for turn in record.turns for e in turn.result.evidence} if record else {}
        )
        if any(key not in available for key in evidence_ids):
            raise ValueError("Select evidence from the source investigation.")
        item.evidence = [available[key] for key in dict.fromkeys(evidence_ids)]
        await asyncio.to_thread(self._repository.confirmed.save, self._printer_id, item)
        return item

    async def forget_confirmed(self, memory_id: str) -> None:
        await asyncio.to_thread(self._repository.confirmed.delete, self._printer_id, memory_id)

    async def begin(
        self, investigation: Investigation, run: PendingInvestigation, owner: str
    ) -> None:
        await asyncio.to_thread(self._repository.runs.begin, investigation, run, owner)
        investigation.pending = run

    async def claim(self, owner: str, before: str) -> Investigation | None:
        thread_id = await asyncio.to_thread(
            self._repository.runs.claim, self._printer_id, owner, before
        )
        return await self.get(thread_id) if thread_id else None

    async def checkpoint(
        self, investigation: Investigation, owner: str, evidence: list[Evidence] | None = None
    ) -> None:
        assert investigation.pending is not None
        await asyncio.to_thread(
            self._repository.runs.checkpoint,
            self._printer_id,
            investigation.id,
            investigation.pending.id,
            owner,
            evidence,
        )

    async def release(self, owner: str) -> None:
        await asyncio.to_thread(self._repository.runs.release, self._printer_id, owner)

    async def open(self, thread_id: str | None, message: str) -> Investigation:
        existing = await self.get(thread_id) if thread_id else None
        if existing is not None:
            return existing
        return Investigation(
            id=thread_id or str(uuid4()), printer_id=self._printer_id, title=message[:100]
        )

    async def get(self, thread_id: str) -> Investigation | None:
        return await asyncio.to_thread(self._repository.get, self._printer_id, thread_id)

    async def recent(self) -> list[Investigation]:
        return await asyncio.to_thread(self._repository.recent, self._printer_id)

    async def delete(self, thread_id: str) -> None:
        await asyncio.to_thread(self._repository.delete, self._printer_id, thread_id)

    async def recall(self, investigation: Investigation, message: str) -> list[Evidence]:
        tokens = set(re.findall(r"[a-z0-9_]{3,}", message.lower())) - {
            "the",
            "and",
            "for",
            "this",
            "that",
            "with",
            "you",
            "can",
            "printer",
            "please",
            "what",
            "how",
        }
        candidates: list[tuple[int, Evidence]] = []
        investigations = [investigation]
        if self._cross_chat:
            investigations.extend(
                item for item in await self.recent() if item.id != investigation.id
            )
        for item in investigations:
            for turn in item.turns[-3:]:
                for evidence in turn.result.evidence:
                    words = set(re.findall(r"[a-z0-9_]{3,}", evidence.content.lower()))
                    score = len(tokens & words)
                    if item.id == investigation.id:
                        score += 100
                    if score:
                        candidates.append((score, evidence))
        candidates.sort(key=lambda item: (item[0], item[1].observed_at), reverse=True)
        selected: dict[tuple[str, str], Evidence] = {}
        for _, evidence in candidates:
            key = (evidence.source, evidence.content)
            selected.setdefault(key, evidence.copy(update={"content": evidence.content[:1200]}))
            if len(selected) == 6:
                break
        statements = [
            item.as_evidence()
            for item in await self.confirmed()
            if (self._cross_chat or item.investigation_id == investigation.id)
            and (
                item.kind == "preference"
                or tokens & set(re.findall(r"[a-z0-9_]{3,}", item.content.lower()))
                or item.investigation_id == investigation.id
            )
        ][:6]
        return statements + list(selected.values())

    async def remember(
        self,
        investigation: Investigation,
        question: str,
        result: InvestigationResult,
        imported_history: list[ChatHistoryMessage],
        owner: str | None = None,
    ) -> InvestigationTurn:
        turn = InvestigationTurn(
            question=question,
            result=result,
            imported_history=imported_history if not investigation.turns else [],
        )
        await asyncio.to_thread(self._repository.save_turn, investigation, turn, owner)
        return turn
