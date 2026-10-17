from __future__ import annotations

import json
from hashlib import sha256
from typing import Literal

from klipperai_agent.domain.knowledge import CachedDocument, ComponentIdentity, KnowledgeSetup
from klipperai_agent.knowledge.sources import component_documents, mapping_evidence


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
        gaps.append("Enter the component model from the printer profile or hardware label.")
    if not component.confirmed or profile_changed:
        gaps.append("Confirm component identity and wiring; saved profile may have changed.")
    evidence = mapping_evidence(component, docs)
    return {
        "role": component.role,
        "model": component.model,
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
