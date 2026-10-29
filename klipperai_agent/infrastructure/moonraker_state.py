"""Fixed core Moonraker reads with bounded public fields and loaded-config metadata."""

from __future__ import annotations

import json
from typing import Any

from klipperai_agent.domain.evidence import ArtifactInput
from klipperai_agent.domain.investigation import utc_now
from klipperai_agent.domain.redaction import redact_text
from klipperai_agent.infrastructure.moonraker import MoonrakerClient, MoonrakerError

CORE_OBJECTS = {
    "webhooks": ["state", "state_message"],
    "print_stats": ["state", "message", "filename", "print_duration", "total_duration"],
    "toolhead": ["homed_axes", "print_time", "estimated_print_time"],
    "extruder": ["temperature", "target", "power"],
    "heater_bed": ["temperature", "target", "power"],
    "configfile": ["config", "save_config_pending", "warnings"],
}


def public_fields(data: dict, names: tuple[str, ...] | list[str]) -> dict:
    result: dict[str, Any] = {}
    for name in names:
        value = data.get(name)
        if value is None or isinstance(value, (bool, int, float)):
            if name in data:
                result[name] = value
        elif isinstance(value, str):
            result[name] = redact_text(value)[:500]
        elif isinstance(value, list):
            result[name] = [redact_text(str(item))[:240] for item in value[:8]]
    return result


async def collect_core_state(
    client: MoonrakerClient, server_info: dict
) -> tuple[ArtifactInput, list[str]]:
    notes: list[str] = []
    state: dict = {
        "observed_at": utc_now(),
        "scope": "Current Moonraker/Klipper state, not historical incident measurements. Loaded config metadata reflects the last Klipper start/restart and may differ from files on disk.",
        "server_info": public_fields(
            server_info,
            (
                "klippy_connected",
                "klippy_state",
                "moonraker_version",
                "warnings",
                "failed_components",
            ),
        ),
        "sources": ["/server/info"],
    }
    try:
        state["printer_info"] = public_fields(
            await client.get_printer_info(),
            ("state", "state_message", "software_version", "cpu_info", "config_file"),
        )
        state["sources"].append("/printer/info")
    except (MoonrakerError, ValueError):
        notes.append("Current Klipper printer info unavailable; server evidence retained.")
    try:
        available = await client.list_printer_objects()
        objects: dict[str, list[str] | None] = {
            name: fields for name, fields in CORE_OBJECTS.items() if name in available
        }
        status = await client.query_printer_objects(objects) if objects else {}
        state["status"] = {
            name: public_fields(status[name], fields or [])
            for name, fields in objects.items()
            if name != "configfile" and isinstance(status.get(name), dict)
        }
        config = status.get("configfile")
        if isinstance(config, dict):
            metadata = public_fields(config, ["save_config_pending"])
            loaded = config.get("config")
            if isinstance(loaded, dict):
                metadata.update(
                    section_count=len(loaded),
                    section_names=[redact_text(str(name))[:80] for name in list(loaded)[:80]],
                    section_names_truncated=len(loaded) > 80,
                )
            warnings = config.get("warnings")
            if isinstance(warnings, list):
                metadata["warnings"] = [
                    public_fields(item, ["type", "message"])
                    for item in warnings[:8]
                    if isinstance(item, dict)
                ]
                metadata["warning_count"] = len(warnings)
            state["config_metadata"] = metadata
        else:
            notes.append("Loaded Klipper config metadata unavailable.")
        state["sources"].extend(["/printer/objects/list", "/printer/objects/query"])
    except (MoonrakerError, ValueError):
        notes.append(
            "Current printer objects/config metadata unavailable; printer may be disconnected or shut down."
        )
    state["collection_notes"] = notes
    return ArtifactInput(
        kind="notes", label="Moonraker core state", content=json.dumps(state, ensure_ascii=True)
    ), notes
