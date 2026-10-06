from __future__ import annotations

from dataclasses import dataclass

from klipperai_agent.config.models import ConfigRequestTarget, ConfigSnapshot
from klipperai_agent.diagnostics.models import DiagnosticsSnapshot
from klipperai_agent.profile.models import PrinterProfile


@dataclass(slots=True)
class ConfigPromptPayload:
    user_message: str
    snapshot: ConfigSnapshot
    target: ConfigRequestTarget
    profile: PrinterProfile
    runtime_snapshot: DiagnosticsSnapshot | None = None
    conversation_context: str = ""
