"""Explicit user records; model tools have no access to these write operations."""

from klipperai_agent.domain.hardware import ConnectorObservation, DiagramNote
from klipperai_agent.domain.investigation import utc_now
from klipperai_agent.domain.knowledge import ComponentIdentity, KnowledgeConflict, KnowledgeSetup
from klipperai_agent.domain.redaction import redact_text
from klipperai_agent.knowledge.buses import connector_identity


def record_connector(setup: KnowledgeSetup, observation: ConnectorObservation) -> KnowledgeSetup:
    component = next((item for item in setup.components if item.role == observation.role), None)
    if component is None or not component.confirmed or not component.revision:
        raise KnowledgeConflict(
            "Confirm the exact component identity and revision before recording physical connectors."
        )
    item = observation.copy(
        update={
            "observed_at": utc_now(),
            "identity_signature": connector_identity(component),
            "attached_device": redact_text(observation.attached_device),
            "electrical_notes": redact_text(observation.electrical_notes),
        }
    )
    entries = [
        entry
        for entry in setup.connectors
        if (entry.role, entry.connector.casefold()) != (item.role, item.connector.casefold())
    ]
    if len(entries) >= 64:
        raise KnowledgeConflict("Connector inventory limit reached.")
    return setup.copy(update={"connectors": [*entries, item]})


def connector_observations(setup: KnowledgeSetup, component: ComponentIdentity) -> list[dict]:
    return [
        {**item.model_dump(), "stale": item.identity_signature != connector_identity(component)}
        for item in setup.connectors
        if item.role == component.role
    ]


def record_diagram(setup: KnowledgeSetup, note: DiagramNote, documents: list) -> KnowledgeSetup:
    document = next(
        (item for item in documents if item.id == note.document_id and item.digest == note.digest),
        None,
    )
    if (
        not note.confirmed
        or document is None
        or not any(page.page == note.page for page in document.pages)
    ):
        raise KnowledgeConflict("Confirm a note against a current cached PDF page and digest.")
    entries = [
        item
        for item in setup.diagram_notes
        if (item.document_id, item.page) != (note.document_id, note.page)
    ]
    if len(entries) >= 64:
        raise KnowledgeConflict("Diagram note limit reached.")
    return setup.copy(
        update={
            "diagram_notes": [
                *entries,
                note.copy(update={"observed_at": utc_now(), "text": redact_text(note.text)}),
            ]
        }
    )
