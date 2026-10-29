"""User-triggered live reads with explicit limits; no printer commands are exposed."""

import asyncio

from klipperai_agent.agent.ports import ConfigReader, PrinterReader
from klipperai_agent.domain.investigation import utc_now
from klipperai_agent.domain.knowledge import KnowledgeSetup
from klipperai_agent.knowledge.firmware import firmware_scope
from klipperai_agent.knowledge.pins import pin_ownership


async def validate_hardware(
    setup: KnowledgeSetup, printer: PrinterReader | None, config: ConfigReader | None
) -> dict:
    report: dict = {
        "checked_at": utc_now(),
        "kind": "live_read_only",
        "printer_reachable": False,
        "physical_wiring_verified": False,
        "provider_checked": False,
        "gaps": [],
        "checks": [],
    }
    if printer is None or config is None:
        report["gaps"].append("A live printer/config reader is not configured.")
        return report
    try:
        info = await asyncio.wait_for(printer.get_printer_info(), 5)
        available = await asyncio.wait_for(printer.list_printer_objects(), 5)
        selected: dict[str, list[str] | None] = {
            name: None
            for name in available
            if name in {"webhooks", "configfile", "toolhead", "extruder", "heater_bed"}
        }
        status = (
            await asyncio.wait_for(printer.query_printer_objects(selected), 5) if selected else {}
        )
        report.update(
            printer_reachable=True,
            state=str(info.get("state", "unknown"))[:80],
            firmware=firmware_scope(setup, str(info.get("software_version", ""))[:200]),
        )
        loaded = status.get("configfile", {}).get("settings", {})
        report["checks"].append({"check": "loaded_configuration_available", "passed": bool(loaded)})
        snapshot = await asyncio.wait_for(asyncio.to_thread(config.collect_with_options), 5)
        owners = pin_ownership(snapshot)
        report["config_revision"] = snapshot.revision()
        report["gaps"].extend(owners["gaps"])
        for component in setup.components:
            report["checks"].append(
                {
                    "check": "configured_mcu",
                    "role": component.role,
                    "mcu": component.mcu,
                    "passed": bool(component.mcu and component.mcu in owners["mcus"]),
                }
            )
        # Expose only fixed public status scalars; never return raw config or paths.
        report["observations"] = {
            name: {
                key: value
                for key, value in values.items()
                if key in {"state", "temperature", "target", "homed_axes", "save_config_pending"}
                and isinstance(value, (str, int, float, bool))
            }
            for name, values in status.items()
            if name in selected and isinstance(values, dict)
        }
        if not report["firmware"]["commit_prefix_matches"]:
            report["gaps"].append(
                "Live firmware was not matched to a selected exact-commit reference."
            )
        if not loaded:
            report["gaps"].append(
                "Loaded firmware settings are unavailable; on-disk config may differ."
            )
    except Exception:
        report["gaps"].append(
            "Live printer validation could not complete. Check Moonraker connectivity and local config collection."
        )
    report["gaps"].append(
        "Physical connectors, electrical ratings and calibration require user verification; successful reads do not establish safe operation."
    )
    return report
