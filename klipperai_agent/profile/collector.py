from __future__ import annotations

import asyncio
from typing import Any

from klipperai_agent.config.collector import ConfigCollector
from klipperai_agent.config.models import ConfigSnapshot
from klipperai_agent.infrastructure.moonraker import MoonrakerClient, MoonrakerError
from klipperai_agent.profile.addons import AddonDetector
from klipperai_agent.profile.capabilities import CapabilityDetector
from klipperai_agent.profile.hardware import HardwareDetector
from klipperai_agent.profile.host import HostDetector
from klipperai_agent.profile.models import (
    PrinterProfile,
    ProfileEvidence,
)
from klipperai_agent.profile.values import _first_non_empty, _string


class PrinterProfileCollector:
    def __init__(
        self,
        moonraker: MoonrakerClient,
        config_collector: ConfigCollector,
        *,
        git_timeout_seconds: float = 4.0,
        mainboard_override: str | None = None,
        toolhead_override: str | None = None,
    ) -> None:
        self._moonraker = moonraker
        self._config_collector = config_collector
        self.host = HostDetector(git_timeout_seconds)
        self.capabilities = CapabilityDetector()
        self.hardware = HardwareDetector()
        self.addons = AddonDetector()
        self._mainboard_override = self._normalize_override(mainboard_override)
        self._toolhead_override = self._normalize_override(toolhead_override)

    async def collect(self, config_snapshot: ConfigSnapshot | None = None) -> PrinterProfile:
        notes: list[str] = []
        evidence: list[ProfileEvidence] = []
        snapshot = config_snapshot or self._config_collector.collect()

        (
            _server_info,
            printer_info,
            object_names,
            system_info,
            update_status,
            serial_devices,
            usb_devices,
        ) = await asyncio.gather(
            self._collect_optional("server info", self._moonraker.get_server_info, notes),
            self._collect_optional("printer info", self._moonraker.get_printer_info, notes),
            self._collect_optional("printer objects", self._moonraker.list_printer_objects, notes),
            self._collect_optional("system info", self._moonraker.get_system_info, notes),
            self._collect_optional("update status", self._moonraker.get_update_status, notes),
            self._collect_optional("serial devices", self._moonraker.list_serial_devices, notes),
            self._collect_optional("usb devices", self._moonraker.list_usb_devices, notes),
        )

        object_names_list = sorted(str(item) for item in object_names or [])
        parsed_config = self.capabilities.parse_documents(snapshot.documents)

        klipper_version_info = self.host.extract_klipper_version_info(update_status)
        firmware_version = _first_non_empty(
            _string(klipper_version_info.get("version")),
            _string(printer_info.get("software_version"))
            if isinstance(printer_info, dict)
            else None,
        )
        klipper_path = (
            _string(printer_info.get("klipper_path")) if isinstance(printer_info, dict) else None
        )
        repo_origin = _first_non_empty(
            _string(klipper_version_info.get("remote_url")),
            await asyncio.to_thread(self.host.detect_git_remote, klipper_path)
            if klipper_path
            else None,
        )
        firmware_flavor = self.host.detect_firmware_flavor(klipper_version_info, repo_origin)
        if firmware_flavor:
            source = "Moonraker update status" if klipper_version_info else "Klipper git remote"
            evidence.append(
                ProfileEvidence(f"Firmware flavor detected as {firmware_flavor}.", source, "high")
            )

        host_model = self.host.detect_host_model(system_info)
        host_distribution = self.host.detect_distribution(system_info)
        services = self.host.extract_services(system_info)
        canbus_interfaces = self.host.extract_canbus_interfaces(system_info)

        mcu_sections = self.hardware.extract_mcu_sections(parsed_config)
        mcu_names = [section["name"] for section in mcu_sections]
        primary_mcu = self.hardware.select_primary_mcu(mcu_sections)
        toolhead_mcu = self.hardware.select_toolhead_mcu(mcu_sections)
        mainboard_mcu = self.hardware.describe_mcu(
            primary_mcu, serial_devices or [], usb_devices or []
        )
        toolhead_board = self.hardware.detect_toolhead_board(
            toolhead_mcu, serial_devices or [], usb_devices or [], snapshot
        )
        mainboard = self.hardware.detect_mainboard(snapshot, primary_mcu)
        toolhead = self.hardware.detect_toolhead(snapshot, toolhead_mcu)
        if self._mainboard_override:
            mainboard = self._mainboard_override
            evidence.append(
                ProfileEvidence(f"Mainboard declared as {mainboard}.", "klipperai.cfg", "high")
            )
        if self._toolhead_override:
            toolhead = self._toolhead_override
            evidence.append(
                ProfileEvidence(f"Toolhead declared as {toolhead}.", "klipperai.cfg", "high")
            )

        addons = self.addons.detect_addons(snapshot, object_names_list, update_status, services)
        probe_type = self.capabilities.detect_probe_type(snapshot, object_names_list)
        accelerometer = self.capabilities.detect_accelerometer(snapshot, object_names_list)
        filament_sensor = self.capabilities.detect_filament_sensor(snapshot)
        bed_mesh_configured = self.capabilities.is_bed_mesh_configured(snapshot, object_names_list)
        input_shaper_configured = self.capabilities.is_input_shaper_configured(
            snapshot, object_names_list
        )
        camera_stack = self.capabilities.detect_camera_stack(addons, services)
        printer_state = (
            _string(printer_info.get("state")) if isinstance(printer_info, dict) else None
        )
        state_message = (
            _string(printer_info.get("state_message")) if isinstance(printer_info, dict) else None
        )

        if (
            toolhead_mcu
            and toolhead_board
            and "toolhead" in str(toolhead_mcu.get("name", "")).lower()
        ):
            evidence.append(
                ProfileEvidence(
                    f"Detected toolhead board {toolhead_board}.", "Klipper MCU config", "medium"
                )
            )
        if mainboard_mcu:
            evidence.append(
                ProfileEvidence(
                    f"Detected mainboard MCU {mainboard_mcu}.", "Moonraker peripherals", "medium"
                )
            )
        if canbus_interfaces:
            evidence.append(
                ProfileEvidence(
                    "CAN bus interfaces detected on host.", "Moonraker system info", "high"
                )
            )
        if probe_type:
            evidence.append(
                ProfileEvidence(
                    f"Probe type detected as {probe_type}.",
                    "Klipper config",
                    "high" if probe_type != "generic" else "medium",
                )
            )
        if accelerometer and accelerometer != "none":
            evidence.append(
                ProfileEvidence(
                    f"Accelerometer detected as {accelerometer}.", "Klipper config", "high"
                )
            )
        if filament_sensor:
            evidence.append(
                ProfileEvidence(
                    f"Filament sensor detected as {filament_sensor}.",
                    "Klipper config",
                    "high" if filament_sensor != "none" else "medium",
                )
            )
        if bed_mesh_configured:
            evidence.append(ProfileEvidence("Bed mesh is configured.", "Klipper config", "high"))
        if input_shaper_configured:
            evidence.append(
                ProfileEvidence("Input shaper is configured.", "Klipper config", "high")
            )
        if camera_stack and camera_stack != "none":
            evidence.append(
                ProfileEvidence(
                    f"Camera stack detected as {camera_stack}.",
                    "Moonraker monitored services",
                    "high",
                )
            )
        if addons:
            for addon in addons[:6]:
                evidence.append(
                    ProfileEvidence(f"Detected addon {addon.name}.", addon.source, addon.confidence)
                )

        return PrinterProfile(
            firmware_flavor=firmware_flavor,
            firmware_version=firmware_version,
            klipper_repo_origin=repo_origin,
            klipper_path=klipper_path,
            printer_state=printer_state,
            state_message=state_message,
            host_model=host_model,
            host_distribution=host_distribution,
            mainboard=mainboard,
            mainboard_mcu=mainboard_mcu,
            toolhead=toolhead,
            toolhead_board=toolhead_board,
            probe_type=probe_type,
            accelerometer=accelerometer,
            filament_sensor=filament_sensor,
            camera_stack=camera_stack,
            bed_mesh_configured=bed_mesh_configured,
            input_shaper_configured=input_shaper_configured,
            services=services,
            canbus_interfaces=canbus_interfaces,
            mcu_names=mcu_names,
            object_names=object_names_list,
            addons=addons,
            notes=notes,
            evidence=evidence,
        )

    async def _collect_optional(
        self,
        label: str,
        func: Any,
        notes: list[str],
    ) -> Any:
        try:
            return await func()
        except MoonrakerError as exc:
            notes.append(f"Could not collect {label}: {exc}")
            return None

    @staticmethod
    def _normalize_override(value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None
