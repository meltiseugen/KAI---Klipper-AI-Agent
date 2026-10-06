from __future__ import annotations

from klipperai_agent.config.requests import ConfigPromptPayload
from klipperai_agent.domain.proposals import ConfigProposal


class ProbeProposal:
    def build(self, payload: ConfigPromptPayload, warnings: list[str]) -> ConfigProposal:
        if payload.profile.probe_type and payload.profile.probe_type not in {"none", "generic"}:
            warnings.append(
                f"The saved printer profile already indicates a {payload.profile.probe_type} probe. Review overlap before adding another probe section."
            )
        return ConfigProposal(
            feature="probe",
            title="Starter probe section",
            target_file="klipperai/probe.cfg",
            config=(
                "[probe]\npin: <PROBE_PIN>\nx_offset: 0\ny_offset: 0\nz_offset: 0\nspeed: 5.0\n"
            ),
            rationale="This provides the minimum structure for a generic probe so offsets and pin mapping can be filled in safely.",
            assumptions=[
                "You want a generic probe scaffold, not a BLTouch-specific or Klicky-specific macro suite.",
            ],
            warnings=["Replace <PROBE_PIN> and set real offsets before use.", *warnings],
        )


class InputShaperProposal:
    def build(self, payload: ConfigPromptPayload, warnings: list[str]) -> ConfigProposal:
        if payload.profile.accelerometer in {None, "none"}:
            warnings.append(
                "The saved printer profile does not show an accelerometer yet. Verify accelerometer setup before treating this as a tuned input-shaper config."
            )
        return ConfigProposal(
            feature="input_shaper",
            title="Starter input shaper block",
            target_file="klipperai/input_shaper.cfg",
            config=(
                "[input_shaper]\n"
                "shaper_type_x: mzv\n"
                "shaper_freq_x: <X_FREQ>\n"
                "shaper_type_y: mzv\n"
                "shaper_freq_y: <Y_FREQ>\n"
            ),
            rationale="This gives the standard input_shaper structure while leaving the calibrated frequencies as explicit placeholders.",
            assumptions=[
                "You will tune the final frequencies from measured resonance data.",
            ],
            warnings=["Replace <X_FREQ> and <Y_FREQ> with real tuned values.", *warnings],
        )


class BedMeshProposal:
    def build(self, payload: ConfigPromptPayload, warnings: list[str]) -> ConfigProposal:
        if payload.profile.probe_type in {None, "none"}:
            warnings.append(
                "The saved printer profile does not show a probe yet. Confirm whether this printer will use a probe or a manual mesh workflow."
            )
        return ConfigProposal(
            feature="bed_mesh",
            title="Starter bed mesh section",
            target_file="klipperai/bed_mesh.cfg",
            config=(
                "[bed_mesh]\n"
                "speed: 120\n"
                "horizontal_move_z: 5\n"
                "mesh_min: <MIN_X>,<MIN_Y>\n"
                "mesh_max: <MAX_X>,<MAX_Y>\n"
                "probe_count: 5,5\n"
            ),
            rationale="This is the core Klipper bed mesh structure with placeholders for printable probe bounds.",
            assumptions=[
                "Your printer already has a working probe or probing method.",
            ],
            warnings=[
                "Replace mesh_min and mesh_max with safe reachable probe coordinates.",
                *warnings,
            ],
        )
