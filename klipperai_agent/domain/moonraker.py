"""Bounded, public Moonraker observations and extension contracts."""

from __future__ import annotations

import math
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Protocol

from klipperai_agent.domain.redaction import redact_text
from klipperai_agent.domain.version import __version__

AGENT_NAME = "klipperai"
AGENT_VERSION = __version__
AGENT_URL = "https://github.com/meltiseugen/KAI---Klipper-AI-Agent"


def capabilities() -> dict:
    # Only this fixed public document is written to Moonraker's database.
    return {
        "schema_version": 1,
        "agent": AGENT_NAME,
        "version": AGENT_VERSION,
        "methods": ["klipperai.capabilities", "klipperai.status", "klipperai.create_ui_session"],
        "events": ["klipperai_ready"],
        "printer_access": "read_only",
        "notifications_version": 1,
    }


SUBSCRIPTIONS = {
    "webhooks": ["state", "state_message"],
    "print_stats": ["state", "filename", "message", "print_duration", "filament_used"],
    "virtual_sdcard": ["progress", "is_active"],
    "extruder": ["temperature", "target"],
    "heater_bed": ["temperature", "target"],
}


def public_scalar(value: Any) -> Any:
    if isinstance(value, str):
        return redact_text(value)[:512]
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, (float, int)) and abs(value) < 1e18 and math.isfinite(value):
        return value
    return None


def gcode_filename(value: str) -> str:
    if (
        not 1 <= len(value) <= 512
        or any(ord(char) < 32 for char in value)
        or any(char in value for char in ("\\", ":", "\x7f"))
        or any(part in {"", ".", ".."} for part in value.split("/"))
    ):
        raise ValueError("Use a relative filename within Moonraker's G-code root.")
    return value


class RemoteMethodError(ValueError):
    def __init__(self, code: int, message: str):
        super().__init__(message)
        self.code = code


class MoonrakerObservation:
    def __init__(self) -> None:
        self.revision = 0
        self.connected = False
        self.registered = False
        self.subscribed = False
        self.metadata_registered = False
        self.klippy_state = "unknown"
        self.status: dict[str, dict] = {}
        self.observed_at: str | None = None
        self.eventtime: float | None = None
        self.error: str | None = None

    def disconnect(self) -> None:
        self.connected = self.registered = self.subscribed = self.metadata_registered = False
        self.klippy_state = "unknown"
        self.eventtime = None
        self.error = "Moonraker agent connection unavailable; retrying."
        self.revision += 1

    def update(self, status: Any, eventtime: Any, *, initial: bool = False) -> None:
        if (
            not isinstance(status, dict)
            or type(eventtime) not in (int, float)
            or not 0 <= eventtime < 1e15
        ):
            raise ValueError("Invalid Moonraker status notification.")
        if not initial and self.eventtime is not None and eventtime < self.eventtime:
            return
        if initial:
            self.status = {}
        for name, fields in SUBSCRIPTIONS.items():
            values = status.get(name)
            if isinstance(values, dict):
                self.status.setdefault(name, {}).update(
                    {key: public_scalar(values[key]) for key in fields if key in values}
                )
        self.eventtime = eventtime
        self.observed_at = datetime.now(timezone.utc).isoformat()
        self.revision += 1

    def snapshot(self) -> dict[str, Any]:
        return {
            "revision": self.revision,
            "connected": self.connected,
            "registered": self.registered,
            "subscribed": self.subscribed,
            "metadata_registered": self.metadata_registered,
            "klippy_state": self.klippy_state,
            "status": deepcopy(self.status),
            "observed_at": self.observed_at,
            "eventtime": self.eventtime,
            "stale": not (self.connected and self.subscribed),
            "error": self.error,
        }


class MoonrakerExtension(Protocol):
    @property
    def state(self) -> MoonrakerObservation: ...
    async def dispatch(self, method: str, params: object) -> dict: ...
