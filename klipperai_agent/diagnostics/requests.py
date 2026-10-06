from __future__ import annotations

from dataclasses import dataclass

from klipperai_agent.config.models import ConfigSnapshot
from klipperai_agent.diagnostics.models import DiagnosticsSnapshot
from klipperai_agent.domain.evidence import IssueFinding
from klipperai_agent.profile.models import PrinterProfile


@dataclass(slots=True)
class DiagnosisPromptPayload:
    user_message: str
    snapshot: DiagnosticsSnapshot
    config_snapshot: ConfigSnapshot
    findings: list[IssueFinding]
    profile: PrinterProfile
    conversation_context: str = ""
