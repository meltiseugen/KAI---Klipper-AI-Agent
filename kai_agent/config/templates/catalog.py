from __future__ import annotations

from typing import Protocol

from kai_agent.config.models import ConfigSnapshot
from kai_agent.config.requests import ConfigPromptPayload
from kai_agent.config.templates.advanced import advanced_proposal
from kai_agent.config.templates.calibration import (
    BedMeshProposal,
    InputShaperProposal,
    ProbeProposal,
)
from kai_agent.config.templates.features import feature_proposal
from kai_agent.config.templates.macros import (
    FilamentProposal,
    GenericProposal,
    MacroProposal,
)
from kai_agent.config.templates.motion import (
    CanbusProposal,
    ExtruderProposal,
    StepperProposal,
)
from kai_agent.config.templates.thermal import (
    FanProposal,
    HeaterProposal,
    SensorProposal,
)
from kai_agent.domain.proposals import ConfigProposal
from kai_agent.profile.models import PrinterProfile


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
        configured = advanced_proposal(payload, warnings) or feature_proposal(payload, warnings)
        if configured is not None:
            return configured
        template = self._templates.get(payload.target.feature, self._templates["generic"])
        return template.build(payload, warnings)

    @staticmethod
    def _common_warnings(snapshot: ConfigSnapshot, profile: PrinterProfile) -> list[str]:
        warnings: list[str] = []
        if not snapshot.has_managed_include("kai"):
            warnings.append(
                "Your current config does not appear to include a kai-managed include path yet. You will need to add one manually."
            )
        if profile.canbus_enabled:
            warnings.append(
                "This printer appears to use CAN-connected hardware. Make sure new pins are assigned under the correct MCU alias."
            )
        return warnings
