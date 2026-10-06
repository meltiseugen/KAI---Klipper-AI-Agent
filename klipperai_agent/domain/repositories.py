from __future__ import annotations

from typing import Protocol

from klipperai_agent.domain.investigation import Investigation, InvestigationTurn


class InvestigationConflict(ValueError):
    """Another request has already advanced this investigation."""


class InvestigationRepository(Protocol):
    def get(self, printer_id: str, investigation_id: str) -> Investigation | None: ...

    def recent(self, printer_id: str, limit: int = 30) -> list[Investigation]: ...

    def save_turn(self, investigation: Investigation, turn: InvestigationTurn) -> None: ...

    def delete(self, printer_id: str, investigation_id: str) -> None: ...
