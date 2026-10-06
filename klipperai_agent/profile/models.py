from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, cast

ProfileConfidence = Literal["low", "medium", "high"]


@dataclass(frozen=True, slots=True)
class ProfileEvidence:
    summary: str
    source: str
    confidence: ProfileConfidence = "medium"


@dataclass(frozen=True, slots=True)
class DetectedAddon:
    name: str
    source: str
    confidence: ProfileConfidence = "medium"
    detail: str | None = None

    def to_state(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "source": self.source,
            "confidence": self.confidence,
            "detail": self.detail,
        }


@dataclass(slots=True)
class PrinterProfile:
    firmware_flavor: str | None = None
    firmware_version: str | None = None
    klipper_repo_origin: str | None = None
    klipper_path: str | None = None
    printer_state: str | None = None
    state_message: str | None = None
    host_model: str | None = None
    host_distribution: str | None = None
    mainboard: str | None = None
    mainboard_mcu: str | None = None
    toolhead: str | None = None
    toolhead_board: str | None = None
    probe_type: str | None = None
    accelerometer: str | None = None
    filament_sensor: str | None = None
    camera_stack: str | None = None
    bed_mesh_configured: bool = False
    input_shaper_configured: bool = False
    services: list[str] = field(default_factory=list)
    canbus_interfaces: list[str] = field(default_factory=list)
    mcu_names: list[str] = field(default_factory=list)
    object_names: list[str] = field(default_factory=list)
    addons: list[DetectedAddon] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    evidence: list[ProfileEvidence] = field(default_factory=list)

    @property
    def canbus_enabled(self) -> bool:
        return bool(self.canbus_interfaces or self._has_can_mcu())

    def _has_can_mcu(self) -> bool:
        return any(
            lowered != "mcu" and ("toolhead" in lowered or "can" in lowered)
            for lowered in (name.lower() for name in self.mcu_names)
        )

    def summary_label(self) -> str:
        parts: list[str] = []
        if self.firmware_flavor:
            if self.firmware_version:
                parts.append(f"{self.firmware_flavor} {self.firmware_version}")
            else:
                parts.append(self.firmware_flavor)
        if self.toolhead_board:
            parts.append(self.toolhead_board)
        elif self.mainboard:
            parts.append(self.mainboard)
        if self.canbus_enabled:
            parts.append("CAN")
        if self.addons:
            visible_addons = [
                addon.name
                for addon in self.addons
                if addon.name.strip() and addon.name.lower() != "sonar"
            ]
            if visible_addons:
                parts.append(", ".join(visible_addons[:2]))
        return " | ".join(parts[:4])

    def to_prompt_block(self) -> str:
        lines: list[str] = []
        if self.summary_label():
            lines.append(f"Profile summary: {self.summary_label()}")
        if self.printer_state:
            lines.append(f"Printer state: {self.printer_state}")
        if self.state_message:
            lines.append(f"Printer state message: {self.state_message}")
        if self.host_model:
            lines.append(f"Host model: {self.host_model}")
        if self.host_distribution:
            lines.append(f"Host distribution: {self.host_distribution}")
        if self.mainboard:
            lines.append(f"Mainboard: {self.mainboard}")
        if self.mainboard_mcu:
            lines.append(f"Mainboard MCU: {self.mainboard_mcu}")
        if self.toolhead:
            lines.append(f"Toolhead: {self.toolhead}")
        if self.toolhead_board:
            lines.append(f"Toolhead board: {self.toolhead_board}")
        if self.probe_type:
            lines.append(f"Probe type: {self.probe_type}")
        if self.accelerometer:
            lines.append(f"Accelerometer: {self.accelerometer}")
        if self.filament_sensor:
            lines.append(f"Filament sensor: {self.filament_sensor}")
        if self.camera_stack:
            lines.append(f"Camera stack: {self.camera_stack}")
        lines.append(f"Bed mesh configured: {'yes' if self.bed_mesh_configured else 'no'}")
        lines.append(f"Input shaper configured: {'yes' if self.input_shaper_configured else 'no'}")
        if self.mcu_names:
            lines.append(f"MCUs: {', '.join(self.mcu_names[:8])}")
        if self.canbus_interfaces:
            lines.append(f"CAN interfaces: {', '.join(self.canbus_interfaces[:4])}")
        if self.addons:
            addon_lines = []
            for addon in self.addons[:8]:
                detail = f" ({addon.detail})" if addon.detail else ""
                addon_lines.append(
                    f"- {addon.name} [{addon.confidence}] via {addon.source}{detail}"
                )
            lines.append("Detected addons:\n" + "\n".join(addon_lines))
        if self.notes:
            lines.append("Profile notes:\n" + "\n".join(f"- {note}" for note in self.notes[:8]))
        return "\n".join(lines) if lines else "No printer profile could be detected."

    def to_state(self) -> dict[str, Any]:
        return {
            "firmware_flavor": self.firmware_flavor,
            "firmware_version": self.firmware_version,
            "klipper_repo_origin": self.klipper_repo_origin,
            "klipper_path": self.klipper_path,
            "printer_state": self.printer_state,
            "state_message": self.state_message,
            "host_model": self.host_model,
            "host_distribution": self.host_distribution,
            "mainboard": self.mainboard,
            "mainboard_mcu": self.mainboard_mcu,
            "toolhead": self.toolhead,
            "toolhead_board": self.toolhead_board,
            "probe_type": self.probe_type,
            "accelerometer": self.accelerometer,
            "filament_sensor": self.filament_sensor,
            "camera_stack": self.camera_stack,
            "bed_mesh_configured": self.bed_mesh_configured,
            "input_shaper_configured": self.input_shaper_configured,
            "services": list(self.services),
            "canbus_interfaces": list(self.canbus_interfaces),
            "mcu_names": list(self.mcu_names),
            "object_names": list(self.object_names),
            "addons": [addon.to_state() for addon in self.addons],
            "notes": list(self.notes),
            "evidence": [
                {
                    "summary": item.summary,
                    "source": item.source,
                    "confidence": item.confidence,
                }
                for item in self.evidence
            ],
        }

    def to_summary(self) -> dict[str, Any]:
        return {
            "firmware_flavor": self.firmware_flavor,
            "firmware_version": self.firmware_version,
            "host_model": self.host_model,
            "host_distribution": self.host_distribution,
            "mainboard": self.mainboard,
            "mainboard_mcu": self.mainboard_mcu,
            "toolhead": self.toolhead,
            "toolhead_board": self.toolhead_board,
            "probe_type": self.probe_type,
            "accelerometer": self.accelerometer,
            "filament_sensor": self.filament_sensor,
            "camera_stack": self.camera_stack,
            "bed_mesh_configured": self.bed_mesh_configured,
            "input_shaper_configured": self.input_shaper_configured,
            "printer_state": self.printer_state,
            "canbus_enabled": self.canbus_enabled,
            "addons": [addon.to_state() for addon in self.addons],
            "summary": self.summary_label(),
        }

    @classmethod
    def from_state(cls, data: dict[str, Any]) -> PrinterProfile:
        addons = [
            DetectedAddon(
                name=str(item.get("name", "")),
                source=str(item.get("source", "unknown")),
                confidence=cast(ProfileConfidence, str(item.get("confidence", "medium"))),
                detail=str(item.get("detail")) if item.get("detail") is not None else None,
            )
            for item in data.get("addons", [])
        ]
        evidence = [
            ProfileEvidence(
                summary=str(item.get("summary", "")),
                source=str(item.get("source", "unknown")),
                confidence=cast(ProfileConfidence, str(item.get("confidence", "medium"))),
            )
            for item in data.get("evidence", [])
        ]
        return cls(
            firmware_flavor=str(data.get("firmware_flavor"))
            if data.get("firmware_flavor")
            else None,
            firmware_version=str(data.get("firmware_version"))
            if data.get("firmware_version")
            else None,
            klipper_repo_origin=str(data.get("klipper_repo_origin"))
            if data.get("klipper_repo_origin")
            else None,
            klipper_path=str(data.get("klipper_path")) if data.get("klipper_path") else None,
            printer_state=str(data.get("printer_state")) if data.get("printer_state") else None,
            state_message=str(data.get("state_message")) if data.get("state_message") else None,
            host_model=str(data.get("host_model")) if data.get("host_model") else None,
            host_distribution=str(data.get("host_distribution"))
            if data.get("host_distribution")
            else None,
            mainboard=str(data.get("mainboard")) if data.get("mainboard") else None,
            mainboard_mcu=str(data.get("mainboard_mcu")) if data.get("mainboard_mcu") else None,
            toolhead=str(data.get("toolhead")) if data.get("toolhead") else None,
            toolhead_board=str(data.get("toolhead_board")) if data.get("toolhead_board") else None,
            probe_type=str(data.get("probe_type")) if data.get("probe_type") else None,
            accelerometer=str(data.get("accelerometer")) if data.get("accelerometer") else None,
            filament_sensor=str(data.get("filament_sensor"))
            if data.get("filament_sensor")
            else None,
            camera_stack=str(data.get("camera_stack")) if data.get("camera_stack") else None,
            bed_mesh_configured=_as_bool(data.get("bed_mesh_configured")),
            input_shaper_configured=_as_bool(data.get("input_shaper_configured")),
            services=[str(item) for item in data.get("services", [])],
            canbus_interfaces=[str(item) for item in data.get("canbus_interfaces", [])],
            mcu_names=[str(item) for item in data.get("mcu_names", [])],
            object_names=[str(item) for item in data.get("object_names", [])],
            addons=addons,
            notes=[str(item) for item in data.get("notes", [])],
            evidence=evidence,
        )


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "on"}
