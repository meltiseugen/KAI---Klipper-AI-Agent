from __future__ import annotations

from dataclasses import replace

from klipperai_agent.config.models import ConfigDocument, ConfigSnapshot
from klipperai_agent.config.parser import ConfigParser
from klipperai_agent.domain.knowledge import CachedDocument, KnowledgeSetup
from klipperai_agent.domain.proposals import ConfigProposal
from klipperai_agent.knowledge.fans import inspect_fan_ports
from klipperai_agent.knowledge.pins import config_rows, pin_ownership


def review_fan_hardware(
    proposal: ConfigProposal,
    snapshot: ConfigSnapshot,
    setup: KnowledgeSetup,
    docs: list[CachedDocument],
    changed: bool,
) -> list[str]:
    draft = ConfigDocument(
        "__proposal__", proposal.config, ConfigParser.extract_sections(proposal.config)
    )
    fan_sections = {
        name
        for name in draft.sections
        if name.split(" ")[0]
        in {"fan", "fan_generic", "heater_fan", "controller_fan", "temperature_fan"}
    }
    if not fan_sections:
        return []
    errors = []
    combined = replace(snapshot, documents=[*snapshot.documents, draft])
    ownership = pin_ownership(combined)
    rows = [
        row
        for row in config_rows(combined)
        if row["path"] == "__proposal__"
        and row["section"] in fan_sections
        and row["option"] == "pin"
    ]
    if {row["section"] for row in rows} != fan_sections or ownership["gaps"]:
        errors.append("Fan hardware review needs complete, resolvable pin configuration.")
    for row in rows:
        canonical = [pin for pin, uses in ownership["owners"].items() if row in uses]
        if not canonical:
            errors.append("Proposed fan pin could not be resolved.")
        for pin in canonical:
            mcu = pin.split(":", 1)[0]
            components = [
                item for item in setup.components if item.mcu == mcu and item.category == "board"
            ]
            if len(components) != 1:
                errors.append("Fan MCU does not have one confirmed component identity.")
                continue
            report = inspect_fan_ports(
                components[0],
                docs,
                changed,
                combined,
                setup.reviewed_fan_mappings.get(components[0].role, ""),
            )
            if report["gaps"] or not any(port["pin"] == pin for port in report["ports"]):
                errors.append(
                    "Fan pin is not verified for this board revision and current configuration."
                )
            conflicts = [
                use
                for use in ownership["owners"][pin]
                if use != row
                and not (use["path"] == proposal.target_file and use["section"] == row["section"])
            ]
            if conflicts:
                errors.append(f"Proposed fan pin {pin} is already used by another active section.")
    return sorted(set(errors))
