"""Conservative pin ownership, including aliases and virtual multi-pin outputs."""

from __future__ import annotations

import re

from klipperai_agent.config.models import ConfigSnapshot
from klipperai_agent.domain.knowledge import MCU_PIN_PATTERN


def config_rows(snapshot: ConfigSnapshot) -> list[dict]:
    rows: list[dict] = []
    for document in snapshot.documents:
        section = ""
        previous: dict | None = None
        previous_indent = 0
        for number, raw in enumerate(document.content.splitlines(), 1):
            line = re.split(r"[#;]", raw, maxsplit=1)[0].strip()
            match = re.match(r"^\[([^]]+)\]", line)
            if match:
                section = match[1].strip()
                previous = None
                continue
            option = re.match(r"^([a-zA-Z_][a-zA-Z0-9_]*)\s*[:=]\s*(.*)$", line)
            indent = len(raw) - len(raw.lstrip())
            if line and previous and indent > previous_indent:
                previous["value"] = (previous["value"] + " " + line).strip()
            elif option:
                previous = {
                    "section": section,
                    "option": option[1].casefold(),
                    "value": option[2],
                    "path": document.path,
                    "line": number,
                }
                previous_indent = indent
                rows.append(previous)
    return rows


def config_gaps(snapshot: ConfigSnapshot) -> list[str]:
    resolved = {
        f"Config content truncated after the opening excerpt: {doc.path}"
        for doc in snapshot.documents
        if not doc.truncated
    }
    return [
        note
        for note in snapshot.notes
        if note not in resolved and not note.startswith("Auto-detected root config file:")
    ]


def pin_ownership(snapshot: ConfigSnapshot) -> dict:
    rows = config_rows(snapshot)
    aliases: dict[tuple[str, str], str] = {}
    virtual: dict[str, str] = {}
    gaps = config_gaps(snapshot)
    if not snapshot.documents or any(doc.truncated for doc in snapshot.documents):
        gaps.append("Configuration is missing or truncated.")
    mcus = {
        name[4:] if name.startswith("mcu ") else "mcu"
        for name in snapshot.section_names
        if name == "mcu" or name.startswith("mcu ")
    }
    for row in rows:
        section, option, value = row["section"], row["option"], row["value"]
        if (section == "board_pins" or section.startswith("board_pins ")) and (
            option == "aliases" or option.startswith("aliases_")
        ):
            targets = next(
                (
                    item["value"]
                    for item in rows
                    if item["section"] == section and item["option"] == "mcu"
                ),
                "mcu",
            )
            for assignment in value.split(","):
                if not assignment.strip():
                    continue
                if "=" not in assignment:
                    gaps.append("An alias could not be resolved.")
                    continue
                alias, pin = (part.strip() for part in assignment.split("=", 1))
                for mcu in targets.split(","):
                    key = (mcu.strip(), alias)
                    if key in aliases and aliases[key] != pin:
                        gaps.append("Conflicting board pin aliases.")
                    aliases[key] = pin
        if section.startswith("multi_pin ") and option == "pins":
            virtual[section[10:]] = value

    def resolve(raw: str, default: str = "mcu", seen: tuple = ()) -> list[str]:
        raw = raw.strip().lstrip("!^~")
        if not raw or raw in {"None", "none"}:
            return []
        if len(seen) > 12 or (default, raw) in seen:
            gaps.append("Cyclic or overly deep pin alias.")
            return []
        visited = (*seen, (default, raw))
        if raw.startswith("multi_pin:"):
            name = raw.split(":", 1)[1]
            if name not in virtual:
                gaps.append("Unresolved multi_pin output.")
                return []
            return [
                pin for part in virtual[name].split(",") for pin in resolve(part, default, visited)
            ]
        if raw in {"probe:z_virtual_endstop"} or raw.endswith(":virtual_endstop"):
            return []
        mcu, pin = raw.split(":", 1) if ":" in raw else (default, raw)
        if (mcu, pin) in aliases:
            return resolve(aliases[(mcu, pin)], mcu, visited)
        if re.fullmatch(MCU_PIN_PATTERN, pin) and mcu in mcus:
            return [f"{mcu}:{pin}"]
        gaps.append(f"Unresolved or reserved pin reference: {raw[:80]}.")
        return []

    owners: dict[str, list[dict]] = {}
    for row in rows:
        section, option = row["section"], row["option"]
        if section == "board_pins" or section.startswith(("board_pins ", "multi_pin ")):
            continue
        if option in {"pin", "pins"} or option.endswith(("_pin", "_pins")):
            for value in row["value"].split(","):
                for pin in resolve(value):
                    owners.setdefault(pin, []).append(row)
    for (mcu, alias), value in aliases.items():
        if re.fullmatch(MCU_PIN_PATTERN, alias) and value.startswith("<"):
            owners.setdefault(f"{mcu}:{alias}", []).append(
                {
                    "section": "board_pins reservation",
                    "path": "configuration",
                    "line": 0,
                    "option": "aliases",
                    "value": value,
                }
            )
    return {
        "owners": owners,
        "gaps": sorted(set(gaps)),
        "mcus": sorted(mcus),
        "rows": rows,
        "buses": bus_reservations(rows, owners),
    }


def bus_reservations(rows: list[dict], owners: dict[str, list[dict]]) -> list[dict]:
    """Keep implicit hardware buses visible, scoped to their MCU where identifiable."""
    sections = {row["section"] for row in rows if not row["section"].startswith("gcode_macro ")}
    result = []
    for section in sorted(sections):
        options = {row["option"]: row["value"] for row in rows if row["section"] == section}
        buses = {key for key in options if key.endswith("_bus")}
        if "cs_pin" in options and "spi_software_sclk_pin" not in options:
            buses.add("spi_bus")  # An omitted bus still reserves the firmware default pins.
        if "i2c_software_scl_pin" not in options and (
            any(key.startswith("i2c_") for key in options)
            or section.startswith("probe_eddy_current ")
        ):
            buses.add("i2c_bus")
        for bus in sorted(buses):
            mcu = None
            if bus == "i2c_bus":
                mcu = options.get("i2c_mcu", "mcu")
            elif bus == "spi_bus":
                chips = {
                    pin.split(":", 1)[0]
                    for pin, uses in owners.items()
                    if any(use["section"] == section and use["option"] == "cs_pin" for use in uses)
                }
                if len(chips) == 1:
                    mcu = next(iter(chips))
            result.append(
                {
                    "section": section,
                    "option": bus,
                    "mcu": mcu,
                    "value": options.get(bus, "firmware default"),
                }
            )
    return result
