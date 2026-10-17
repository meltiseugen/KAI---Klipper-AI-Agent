from __future__ import annotations

from klipperai_agent.config.models import ConfigSnapshot
from klipperai_agent.domain.knowledge import CachedDocument, KnowledgeSetup
from klipperai_agent.knowledge.pins import config_gaps, config_rows
from klipperai_agent.knowledge.retrieval import search_documents
from klipperai_agent.knowledge.sources import component_documents


def inspect_eddy(
    setup: KnowledgeSetup,
    docs: list[CachedDocument],
    changed: bool,
    snapshot: ConfigSnapshot,
    symptom: str,
) -> dict:
    probe = next((item for item in setup.components if item.role == "probe"), None)
    gaps = config_gaps(snapshot)
    if (
        not probe
        or "eddy" not in probe.model.casefold()
        or not probe.confirmed
        or not probe.mcu
        or probe.connection == "unknown"
        or changed
    ):
        gaps.append("Confirm the exact Eddy variant and its connection/MCU in Printer knowledge.")
    if not setup.firmware_flavor or not setup.firmware_version:
        gaps.append(
            "Installed firmware flavor/version unknown; a calibration procedure cannot be matched reliably."
        )
    gaps.append(
        "Cached vendor/current-upstream guides are not verified against the installed firmware commit. Research the matching fork/version before recommending a calibration procedure."
    )
    if any(doc.truncated for doc in snapshot.documents) or not snapshot.documents:
        gaps.append("Active configuration is incomplete.")
    sections = [
        name
        for name in snapshot.section_names
        if name.startswith(
            (
                "probe_eddy_current ",
                "temperature_probe ",
                "bed_mesh",
                "safe_z_home",
                "homing_override",
                "z_tilt",
                "quad_gantry_level",
            )
        )
        or "START" in name.upper()
    ]
    all_rows = config_rows(snapshot)
    rows = [row for row in all_rows if row["section"] in sections]
    probe_names = {
        name.split(" ", 1)[1] for name in sections if name.startswith("probe_eddy_current ")
    }
    thermal_names = {
        name.split(" ", 1)[1] for name in sections if name.startswith("temperature_probe ")
    }
    if not probe_names:
        gaps.append(
            "No active probe_eddy_current section found. Check the installed Eddy extension/fork and its documentation before suggesting commands."
        )
    if thermal_names - probe_names:
        gaps.append(
            "Temperature-probe names do not match the eddy-probe names; review thermal compensation linkage."
        )
    if probe_names - thermal_names:
        gaps.append(
            "An eddy probe has no matching temperature_probe section; check thermal compensation support and configuration."
        )
    if probe and probe.mcu:
        mcu_section = "mcu" if probe.mcu == "mcu" else f"mcu {probe.mcu}"
        if mcu_section not in snapshot.section_names:
            gaps.append("Saved Eddy MCU is absent from the active configuration.")
        for name in probe_names:
            mcu = next(
                (
                    row["value"]
                    for row in rows
                    if row["section"] == f"probe_eddy_current {name}" and row["option"] == "i2c_mcu"
                ),
                "mcu",
            )
            if mcu != probe.mcu:
                gaps.append(f"Probe {name} uses MCU {mcu}, which differs from the saved Eddy MCU.")
        connections = {row["option"] for row in all_rows if row["section"] == mcu_section}
        if ("canbus_uuid" in connections and probe.connection != "CAN") or (
            "serial" in connections and probe.connection == "CAN"
        ):
            gaps.append("Saved Eddy connection type conflicts with active MCU configuration.")
    calibration = [
        {"path": doc.path, "line": index + 1, "text": line[:250]}
        for doc in snapshot.documents
        for index, line in enumerate(doc.content.splitlines())
        if any(
            token in line
            for token in ("#*# calibrate", "#*# drift_calibration", "#*# calibration_temp")
        )
    ][:12]
    passages = search_documents(
        docs,
        symptom + " calibration thermal drift offsets homing",
        {doc.id for doc in component_documents(probe, docs)} if probe else set(),
    )
    if not passages:
        gaps.append(
            "No cached Eddy guidance matched; build knowledge or search official documentation."
        )
    return {
        "firmware": {"flavor": setup.firmware_flavor, "version": setup.firmware_version},
        "sections": sections[:30],
        "configuration": rows[:45],
        "configuration_truncated": len(rows) > 45 or len(sections) > 30,
        "saved_calibration_markers": calibration,
        "gaps": gaps,
        "passages": passages,
        "next_checks": [
            "Distinguish mesh shape, first-layer height, probing errors and temperature-related drift.",
            "Compare sensor mounting/offsets, calibration and temperature conditions with the matching vendor and firmware documentation.",
            "Inspect start macros and whether the expected mesh and probe calibration are used; do not assume every bed fault originates in Eddy.",
        ],
        "scope": "Cached guides carry source hashes and retrieval dates, not a guarantee of compatibility with installed firmware. Verify fork/version-specific commands before giving a manual procedure. No movement, heating, calibration or SAVE_CONFIG is executed.",
    }
