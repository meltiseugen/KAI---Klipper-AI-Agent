from __future__ import annotations

import re

from klipperai_agent.profile.models import (
    DetectedAddon,
    PrinterProfile,
    ProfileEvidence,
)
from klipperai_agent.runtime.settings import Settings


def build_profile_from_settings(settings: Settings) -> PrinterProfile:
    addon_names = _split_addon_names(settings.addons)
    persisted_toolhead_board = settings.toolhead or settings.toolhead_board
    return PrinterProfile(
        firmware_flavor=settings.firmware_flavor,
        firmware_version=settings.firmware_version,
        host_model=settings.host_model,
        host_distribution=settings.host_distribution,
        mainboard=settings.mainboard,
        mainboard_mcu=settings.mainboard_mcu,
        toolhead=None,
        toolhead_board=persisted_toolhead_board,
        probe_type=settings.probe_type,
        accelerometer=settings.accelerometer,
        filament_sensor=settings.filament_sensor,
        camera_stack=settings.camera_stack,
        bed_mesh_configured=settings.bed_mesh_configured,
        input_shaper_configured=settings.input_shaper_configured,
        addons=[
            DetectedAddon(
                name=name,
                source="klipperai.cfg",
                confidence="high",
            )
            for name in addon_names
        ],
        evidence=[
            ProfileEvidence("Printer profile loaded from klipperai.cfg.", "klipperai.cfg", "high"),
        ],
        notes=[
            "Static printer profile loaded from klipperai.cfg.",
        ],
        canbus_interfaces=["configured"] if settings.canbus_enabled else [],
    )


def _split_addon_names(value: str | None) -> list[str]:
    if not value:
        return []
    parts = [item.strip() for item in re.split(r"[,\n;]+", value) if item.strip()]
    seen: set[str] = set()
    ordered: list[str] = []
    for part in parts:
        lowered = part.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        ordered.append(part)
    return ordered
