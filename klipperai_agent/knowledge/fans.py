from __future__ import annotations

from klipperai_agent.config.models import ConfigSnapshot
from klipperai_agent.domain.hardware import ConnectorObservation
from klipperai_agent.domain.knowledge import CachedDocument, ComponentIdentity
from klipperai_agent.knowledge.buses import connector_identity, resolved_ownership
from klipperai_agent.knowledge.identity import component_status
from klipperai_agent.knowledge.sources import component_documents


def inspect_fan_ports(
    component: ComponentIdentity,
    documents: list[CachedDocument],
    changed: bool,
    snapshot: ConfigSnapshot,
    reviewed: str = "",
    reviewed_buses: str = "",
    inventory: list[ConnectorObservation] | None = None,
) -> dict:
    status = component_status(component, documents, changed, reviewed)
    evidence = status.pop("fan_evidence")
    pins = resolved_ownership(snapshot, component, documents, reviewed_buses)
    gaps = status["gaps"] + pins["gaps"]
    gaps.extend(
        "Hardware bus pin reservations need review: " + bus["section"] + " / " + bus["option"]
        for bus in pins["buses"]
        if bus["mcu"] in {None, component.mcu} and not bus["resolved"]
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
            physical = next(
                (
                    item
                    for item in (inventory or [])
                    if item.role == component.role
                    and item.connector.casefold() == connector.casefold()
                ),
                None,
            )
            current = bool(
                physical and physical.identity_signature == connector_identity(component)
            )
            occupied = bool(current and physical and physical.occupancy == "occupied")
            ports.append(
                {
                    "connector": connector,
                    "pin": canonical if not gaps else None,
                    "status": "in use"
                    if uses or occupied
                    else "needs information"
                    if gaps
                    else "user-confirmed free; verify before wiring"
                    if current and physical and physical.occupancy == "free"
                    else "unused in configuration; physical occupancy unconfirmed",
                    "physical_observation": physical.model_dump() if physical else None,
                    "physical_observation_stale": bool(physical and not current),
                    "electrical_verified_by_user": bool(
                        current and physical and physical.electrical_confirmed
                    ),
                    "uses": uses[:12],
                    "example": f"[fan_generic additional_fan]\npin: {canonical}\n"
                    if not gaps and not uses and not occupied
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
