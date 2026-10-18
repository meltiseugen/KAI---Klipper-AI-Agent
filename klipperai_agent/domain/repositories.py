from __future__ import annotations

from typing import Protocol

from klipperai_agent.domain.investigation import (
    ConfirmedMemory,
    Evidence,
    Investigation,
    InvestigationTurn,
    PendingInvestigation,
)


class InvestigationConflict(ValueError):
    """Another request has already advanced this investigation."""


class InvestigationRepository(Protocol):
    runs: RunRepository
    confirmed: ConfirmedMemoryRepository

    def get(self, printer_id: str, investigation_id: str) -> Investigation | None: ...

    def recent(self, printer_id: str, limit: int = 30) -> list[Investigation]: ...

    def save_turn(
        self, investigation: Investigation, turn: InvestigationTurn, owner: str | None = None
    ) -> None: ...

    def delete(self, printer_id: str, investigation_id: str) -> None: ...


class RunRepository(Protocol):
    def begin(
        self, investigation: Investigation, run: PendingInvestigation, owner: str
    ) -> None: ...

    def claim(self, printer_id: str, owner: str, before: str) -> str | None: ...

    def checkpoint(
        self,
        printer_id: str,
        thread_id: str,
        run_id: str,
        owner: str,
        evidence: list[Evidence] | None = None,
    ) -> None: ...

    def release(self, printer_id: str, owner: str) -> None: ...


class ConfirmedMemoryRepository(Protocol):
    def list(self, printer_id: str) -> list[ConfirmedMemory]: ...

    def save(self, printer_id: str, memory: ConfirmedMemory) -> None: ...

    def delete(self, printer_id: str, memory_id: str) -> None: ...
