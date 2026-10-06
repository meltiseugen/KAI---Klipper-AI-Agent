"""Conversation history and relevant historical evidence for one configured printer."""

from __future__ import annotations

import asyncio
import re
from uuid import uuid4

from klipperai_agent.domain.investigation import (
    Evidence,
    Investigation,
    InvestigationResult,
    InvestigationTurn,
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
        return list(selected.values())

    async def remember(
        self,
        investigation: Investigation,
        question: str,
        result: InvestigationResult,
        imported_history: list[ChatHistoryMessage],
    ) -> InvestigationTurn:
        turn = InvestigationTurn(
            question=question,
            result=result,
            imported_history=imported_history if not investigation.turns else [],
        )
        await asyncio.to_thread(self._repository.save_turn, investigation, turn)
        return turn
