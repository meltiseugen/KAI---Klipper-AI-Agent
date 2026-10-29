"""Fixed component families and evidence-oriented manual diagnostic checks."""

from typing import Literal

from klipperai_agent.config.models import ConfigSnapshot
from klipperai_agent.domain.knowledge import CachedDocument, ComponentIdentity, KnowledgeSetup
from klipperai_agent.knowledge.buses import resolved_ownership
from klipperai_agent.knowledge.firmware import firmware_key
from klipperai_agent.knowledge.retrieval import search_documents
from klipperai_agent.knowledge.sources import component_documents

ComponentFamily = Literal["accelerometer", "probe", "driver", "temperature", "filament"]
FAMILIES = {
    "accelerometer": ("adxl345", "lis2dw", "lis3dh", "mpu9250", "icm20948", "resonance_tester"),
    "probe": ("probe", "bltouch", "probe_eddy_current", "bed_mesh", "safe_z_home"),
    "driver": ("tmc2209", "tmc2208", "tmc2130", "tmc2240", "tmc2660", "tmc5160"),
    "temperature": (
        "temperature_sensor",
        "temperature_fan",
        "heater_bed",
        "extruder",
        "thermistor",
        "adc_temperature",
    ),
    "filament": ("filament_switch_sensor", "filament_motion_sensor"),
}
CHECKS = {
    "accelerometer": [
        "Compare SPI/I2C bus, MCU assignment, chip select/address and axes_map with the exact sensor and source revision.",
        "Inspect mounting and power before any user-run measurement. No resonance test was executed.",
    ],
    "probe": [
        "Compare probe identity, pins, offsets, sampling and homing macros before any supervised motion.",
        "Check trigger state and physical clearance manually. No probing or calibration was executed.",
    ],
    "driver": [
        "Compare the named driver's UART/SPI pins, address, current and complete fault flags with its documentation.",
        "Inspect jumpers, motor power and wiring with power off. No driver register command or motor movement was executed.",
    ],
    "temperature": [
        "Compare sensor_type, sensor_pin and configured range with the actual hardware and source.",
        "Check plausible ambient readings and wiring before supervised heating. No heater command was executed.",
    ],
    "filament": [
        "Compare switch/motion sensor type, pin polarity, detection length and runout macro dependencies.",
        "Observe the physical sensor and reported state manually. No filament motion, pause or runout action was executed.",
    ],
}


def matches_family(name: str, family: ComponentFamily) -> bool:
    return any(name == prefix or name.startswith(prefix + " ") for prefix in FAMILIES[family])


def inspect_component(
    setup: KnowledgeSetup,
    docs: list[CachedDocument],
    component: ComponentIdentity,
    family: ComponentFamily,
    snapshot: ConfigSnapshot,
    changed: bool,
) -> dict:
    ownership = resolved_ownership(
        snapshot, component, docs, setup.reviewed_bus_mappings.get(component.role, "")
    )
    rows = [row for row in ownership["rows"] if matches_family(row["section"], family)][:80]
    ids = {doc.id for doc in component_documents(component, docs)} | {
        doc.id for doc in docs if setup.firmware_commit and doc.component_key == firmware_key(setup)
    }
    gaps = list(ownership["gaps"])
    if changed or not component.confirmed:
        gaps.append("Confirm the current component identity and MCU assignment.")
    if not rows:
        gaps.append("No supported configuration sections for this family were observed.")
    relevant_buses = [bus for bus in ownership["buses"] if matches_family(bus["section"], family)]
    if any(not bus["resolved"] for bus in relevant_buses):
        gaps.append(
            "Some hardware bus pins remain unresolved; review exact source pinmux evidence before claiming availability."
        )
    return {
        "component": component.model_dump(),
        "family": family,
        "configuration": rows,
        "buses": relevant_buses,
        "pin_owners": {
            pin: uses
            for pin, uses in ownership["owners"].items()
            if any(matches_family(use["section"], family) for use in uses)
        },
        "passages": search_documents(docs, family + " " + component.model, ids),
        "manual_checks": CHECKS[family],
        "gaps": sorted(set(gaps)),
        "config_revision": snapshot.revision(),
        "scope": "On-disk configuration and saved source evidence. Status observations do not verify physical wiring, calibration or firmware compatibility.",
    }
