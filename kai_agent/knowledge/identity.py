from __future__ import annotations

import json
from hashlib import sha256
from typing import Literal

from kai_agent.domain.knowledge import CachedDocument, ComponentIdentity, KnowledgeSetup
from kai_agent.knowledge.repositories import repository_location
from kai_agent.knowledge.sources import component_documents, component_key, mapping_evidence


def reference_metadata(setup: KnowledgeSetup, document: CachedDocument) -> dict:
    return {
        **document.model_dump(
            exclude={"content": True, "fan_mappings": True, "pages": {"__all__": {"text"}}}
        ),
        "component_roles": [
            item.role for item in setup.components if component_key(item) == document.component_key
        ],
        "confirmed": setup.confirmed_documents.get(document.id) == document.digest,
        "confirmation_stale": document.id in setup.confirmed_documents
        and setup.confirmed_documents[document.id] != document.digest,
        "excerpt": "Repository index only. Research this component again to cache manuals and configuration examples from inside the repository."
        if repository_location(document.url)
        else document.content.strip()[:600],
    }


def profile_setup(profile: dict) -> KnowledgeSetup:
    roles: dict[str, tuple[str, Literal["board", "probe", "device"]]] = {
        "mainboard": ("mainboard", "board"),
        "toolhead": ("toolhead_board", "board"),
        "probe": ("probe_type", "probe"),
        "accelerometer": ("accelerometer", "device"),
        "filament_sensor": ("filament_sensor", "device"),
        "camera": ("camera_stack", "device"),
    }
    values = {
        key: profile.get(key) or ""
        for key in (*[item[0] for item in roles.values()], "firmware_flavor", "firmware_version")
    }
    return KnowledgeSetup(
        components=[
            ComponentIdentity(role=role, category=category, model=values[key][:120])
            for role, (key, category) in roles.items()
            if values[key] or role in {"mainboard", "toolhead", "probe"}
        ],
        firmware_flavor=values["firmware_flavor"][:80],
        firmware_version=values["firmware_version"][:120],
        profile_signature=sha256(json.dumps(values, sort_keys=True).encode()).hexdigest(),
    )


def component_status(
    component: ComponentIdentity,
    documents: list[CachedDocument],
    profile_changed: bool,
    reviewed: str = "",
) -> dict:
    docs = component_documents(component, documents)
    gaps = []
    if not component.model.strip():
        gaps.append(
            "Exact built-in sensor model is unknown; inspect the containing board's documentation."
            if component.integrated_into
            else "Enter the component model from the printer profile or hardware label."
        )
    if not component.confirmed or profile_changed:
        gaps.append("Confirm component identity and wiring; saved profile may have changed.")
    evidence = mapping_evidence(component, docs)
    return {
        "role": component.role,
        "model": component.model,
        "integrated_into": component.integrated_into,
        "status": "Needs details"
        if gaps
        else "Documentation unavailable"
        if not docs
        else "Documentation cached",
        "gaps": gaps,
        "document_ids": [doc.id for doc in docs],
        "fan_evidence": evidence,
        "fan_mappings_reviewed": bool(
            evidence["signature"]
            and evidence["signature"] == reviewed
            and not evidence["conflicts"]
        ),
    }
