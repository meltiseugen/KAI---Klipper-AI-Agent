from __future__ import annotations

from typing import Protocol

from klipperai_agent.config.models import ConfigSnapshot
from klipperai_agent.config.requests import ConfigPromptPayload
from klipperai_agent.config.templates.calibration import (
    BedMeshProposal,
    InputShaperProposal,
    ProbeProposal,
)
from klipperai_agent.config.templates.macros import (
    FilamentProposal,
    GenericProposal,
    MacroProposal,
)
from klipperai_agent.config.templates.motion import (
    CanbusProposal,
    ExtruderProposal,
    StepperProposal,
)
from klipperai_agent.config.templates.thermal import (
    FanProposal,
    HeaterProposal,
    SensorProposal,
)
from klipperai_agent.domain.proposals import ConfigProposal
from klipperai_agent.profile.models import PrinterProfile


class ProposalTemplate(Protocol):
    def build(self, payload: ConfigPromptPayload, warnings: list[str]) -> ConfigProposal: ...


class ProposalCatalog:
    """Select a small proposal strategy without coupling it to a provider."""

    def __init__(self) -> None:
        self._templates: dict[str, ProposalTemplate] = {
            "fan": FanProposal(),
            "sensor": SensorProposal(),
            "heater": HeaterProposal(),
            "canbus": CanbusProposal(),
            "stepper": StepperProposal(),
            "extruder": ExtruderProposal(),
            "probe": ProbeProposal(),
            "input_shaper": InputShaperProposal(),
            "bed_mesh": BedMeshProposal(),
            "macro": MacroProposal(),
            "filament": FilamentProposal(),
            "generic": GenericProposal(),
        }

    def build(self, payload: ConfigPromptPayload) -> ConfigProposal:
        warnings = self._common_warnings(payload.snapshot, payload.profile)
        template = self._templates.get(payload.target.feature, self._templates["generic"])
        return template.build(payload, warnings)

    @staticmethod
    def _common_warnings(snapshot: ConfigSnapshot, profile: PrinterProfile) -> list[str]:
        warnings: list[str] = []
        if not snapshot.has_managed_include("klipperai"):
            warnings.append(
                "Your current config does not appear to include a klipperai-managed include path yet. You will need to add one manually."
            )
        if profile.canbus_enabled:
            warnings.append(
                "This printer appears to use CAN-connected hardware. Make sure new pins are assigned under the correct MCU alias."
            )
        return warnings
