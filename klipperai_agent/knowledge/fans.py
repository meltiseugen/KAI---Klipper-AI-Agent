from __future__ import annotations

from klipperai_agent.config.models import ConfigSnapshot
from klipperai_agent.domain.knowledge import CachedDocument, ComponentIdentity
from klipperai_agent.knowledge.identity import component_status
from klipperai_agent.knowledge.pins import pin_ownership
from klipperai_agent.knowledge.sources import component_documents


def inspect_fan_ports(
    component: ComponentIdentity,
    documents: list[CachedDocument],
    changed: bool,
    snapshot: ConfigSnapshot,
    reviewed: str = "",
) -> dict:
    status = component_status(component, documents, changed, reviewed)
    evidence = status.pop("fan_evidence")
    pins = pin_ownership(snapshot)
    gaps = status["gaps"] + pins["gaps"]
    gaps.extend(
        "Hardware bus pin reservations need review: " + bus["section"] + " / " + bus["option"]
        for bus in pins["buses"]
        if bus["mcu"] in {None, component.mcu}
    )
    if component.category != "board" or not component.revision or component.connection == "unknown":
        gaps.append(
            "Confirm the exact board revision, MCU and connection before selecting a fan connector."
        )
    if not status["fan_mappings_reviewed"]:
        gaps.append(
            "Build knowledge and review the downloaded connector evidence for this exact board revision in Printer knowledge."
        )
    if evidence["conflicts"]:
        gaps.append(
            "Sources disagree about connector mappings: " + ", ".join(evidence["conflicts"])
        )
    if component.mcu not in pins["mcus"]:
        gaps.append("Component MCU is absent from the active configuration.")
    duplicates = [
        row
        for row in pins["rows"]
        if row["section"] == ("mcu" if component.mcu == "mcu" else f"mcu {component.mcu}")
        and row["option"] in {"serial", "canbus_uuid"}
    ]
    if any(row["option"] == "canbus_uuid" for row in duplicates) and component.connection != "CAN":
        gaps.append("Saved connection conflicts with active CAN configuration.")
    if any(row["option"] == "serial" for row in duplicates) and component.connection == "CAN":
        gaps.append("Saved CAN connection conflicts with an active serial connection.")
    ports = []
    if evidence["candidates"]:
        for connector, pin in sorted(
            {(item["connector"], item["pin"]) for item in evidence["candidates"]}
        ):
            canonical = f"{component.mcu}:{pin}"
            uses = pins["owners"].get(canonical, [])
            ports.append(
                {
                    "connector": connector,
                    "pin": canonical if not gaps else None,
                    "status": "in use"
                    if uses
                    else "needs information"
                    if gaps
                    else "unused in configuration; physical occupancy unconfirmed",
                    "uses": uses[:12],
                    "example": f"[fan_generic additional_fan]\npin: {canonical}\n"
                    if not gaps and not uses
                    else None,
                }
            )
    return {
        "component": status,
        "ports": ports,
        "gaps": sorted(set(gaps)),
        "config_revision": snapshot.revision(),
        "electrical_checks": list(
            dict.fromkeys(
                item["electrical"] for item in evidence["candidates"] if item["electrical"]
            )
        )
        or ["Verify voltage/current limits in the source and on the hardware."],
        "sources": [
            {"title": doc.title, "url": doc.url}
            for doc in component_documents(component, documents)
        ],
        "scope": "Examples use fan_generic for an independently controlled fan. Select fan/heater_fan/controller_fan/temperature_fan according to its purpose. Confirm physical occupancy, voltage, current and connector selection before manual edits.",
    }
