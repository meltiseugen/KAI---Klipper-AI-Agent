"""Source-quoted bus pins; never infer a pinmux from a similar board."""

import json
import re
from hashlib import sha256

from klipperai_agent.config.models import ConfigSnapshot
from klipperai_agent.domain.hardware import BusMapping
from klipperai_agent.domain.knowledge import MCU_PIN_PATTERN, CachedDocument, ComponentIdentity
from klipperai_agent.knowledge.pins import pin_ownership
from klipperai_agent.knowledge.sources import component_documents, component_key


def extract_bus_mappings(text: str) -> list[BusMapping]:
    patterns = (
        r'DECL_CONSTANT_STR\(\s*"BUS_PINS_([A-Za-z0-9_]+)"\s*,\s*"([^"\n]+)"\s*\)',
        r"\bBUS_PINS_([A-Za-z0-9_]+)\s*=\s*([A-Za-z0-9_.,]+)",
    )
    result = []
    for pattern in patterns:
        for match in re.finditer(pattern, text):
            pins = [pin.strip() for pin in match[2].split(",")]
            if 1 <= len(pins) <= 8 and all(re.fullmatch(MCU_PIN_PATTERN, pin) for pin in pins):
                result.append(BusMapping(bus=match[1], pins=pins, quote=match[0][:1200]))
    return result[:64]


def bus_evidence(component: ComponentIdentity, documents: list[CachedDocument]) -> dict:
    candidates = []
    for doc in component_documents(component, documents):
        # Re-extract from retained text, rather than trusting stored/provider mappings.
        for mapping in extract_bus_mappings(doc.content):
            candidates.append(
                {**mapping.model_dump(), "source_id": doc.id, "digest": doc.digest, "url": doc.url}
            )
    variants: dict[str, set[tuple]] = {}
    for item in candidates:
        variants.setdefault(item["bus"], set()).add(tuple(item["pins"]))
    signature = (
        sha256(
            json.dumps(
                [component_key(component), component.mcu, component.connection, candidates],
                sort_keys=True,
            ).encode()
        ).hexdigest()
        if candidates
        else ""
    )
    return {
        "candidates": candidates,
        "signature": signature,
        "conflicts": sorted(bus for bus, values in variants.items() if len(values) > 1),
    }


def resolved_ownership(
    snapshot: ConfigSnapshot,
    component: ComponentIdentity,
    documents: list[CachedDocument],
    reviewed: str = "",
) -> dict:
    pins = pin_ownership(snapshot)
    evidence = bus_evidence(component, documents)
    ready = bool(
        component.confirmed
        and component.revision
        and reviewed
        and reviewed == evidence["signature"]
        and not evidence["conflicts"]
    )
    for bus in pins["buses"]:
        candidates = [item for item in evidence["candidates"] if item["bus"] == bus["value"]]
        bus["resolved"] = False
        if (
            ready
            and bus["mcu"] == component.mcu
            and candidates
            and bus["value"] != "firmware default"
        ):
            item = candidates[0]
            bus.update(
                resolved=True,
                pins=[f"{component.mcu}:{pin}" for pin in item["pins"]],
                source_url=item["url"],
                source_digest=item["digest"],
            )
            for pin in bus["pins"]:
                pins["owners"].setdefault(pin, []).append(
                    {
                        "section": bus["section"],
                        "option": bus["option"],
                        "value": bus["value"],
                        "path": item["url"],
                        "line": 0,
                        "bus_reservation": True,
                    }
                )
    return pins


def connector_identity(component: ComponentIdentity) -> str:
    return sha256(
        json.dumps(
            [component_key(component), component.mcu, component.connection], sort_keys=True
        ).encode()
    ).hexdigest()
