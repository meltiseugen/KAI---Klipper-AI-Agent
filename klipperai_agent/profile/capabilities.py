from __future__ import annotations

import re
from typing import Any

from klipperai_agent.config.models import ConfigDocument, ConfigSnapshot
from klipperai_agent.profile.models import (
    DetectedAddon,
)


class CapabilityDetector:
    _SECTION_PATTERN = re.compile(r"^\s*\[([^\]]+)\]\s*$")

    _OPTION_PATTERN = re.compile(r"^\s*([A-Za-z0-9_.-]+)\s*[:=]\s*(.*?)\s*$")

    def parse_documents(self, documents: list[ConfigDocument]) -> list[dict[str, Any]]:
        parsed: list[dict[str, Any]] = []
        for document in documents:
            current_section: str | None = None
            current_options: dict[str, str] = {}
            for raw_line in document.content.splitlines():
                line = raw_line.strip()
                if not line or line.startswith("#"):
                    continue
                section_match = self._SECTION_PATTERN.match(line)
                if section_match:
                    if current_section is not None:
                        parsed.append(
                            {
                                "section": current_section,
                                "options": current_options,
                                "path": document.path,
                            }
                        )
                    current_section = section_match.group(1).strip()
                    current_options = {}
                    continue
                option_match = self._OPTION_PATTERN.match(raw_line)
                if option_match and current_section is not None:
                    current_options[option_match.group(1).strip().lower()] = option_match.group(
                        2
                    ).strip()
            if current_section is not None:
                parsed.append(
                    {
                        "section": current_section,
                        "options": current_options,
                        "path": document.path,
                    }
                )
        return parsed

    def detect_probe_type(self, snapshot: ConfigSnapshot, object_names: list[str]) -> str:
        config_sections = [section.lower() for section in snapshot.section_names]
        object_haystack = [name.lower() for name in object_names]
        document_haystack = [document.path.lower() for document in snapshot.documents]
        catalog = (
            ("beacon", ("beacon",)),
            ("eddy", ("probe_eddy_current", "eddy")),
            ("cartographer", ("cartographer",)),
            ("klicky", ("klicky", "dockable_probe")),
            ("bltouch", ("bltouch", "probe:z_virtual_endstop")),
        )
        haystacks = [*config_sections, *object_haystack, *document_haystack]
        for label, keywords in catalog:
            if any(keyword in haystack for haystack in haystacks for keyword in keywords):
                return label
        if any(section == "probe" for section in config_sections):
            return "generic"
        return "none"

    def detect_accelerometer(self, snapshot: ConfigSnapshot, object_names: list[str]) -> str:
        config_sections = [section.lower() for section in snapshot.section_names]
        object_haystack = [name.lower() for name in object_names]
        haystacks = [*config_sections, *object_haystack]
        if any("adxl345" in value for value in haystacks):
            return "adxl345"
        if any("lis2dw" in value for value in haystacks):
            return "lis2dw"
        if any("resonance_tester" in value for value in haystacks):
            return "generic"
        return "none"

    def detect_filament_sensor(self, snapshot: ConfigSnapshot) -> str:
        config_sections = [section.lower() for section in snapshot.section_names]
        if any(section.startswith("filament_motion_sensor") for section in config_sections):
            return "motion"
        if any(section.startswith("filament_switch_sensor") for section in config_sections):
            return "switch"
        return "none"

    def is_bed_mesh_configured(self, snapshot: ConfigSnapshot, object_names: list[str]) -> bool:
        if any(section.lower() == "bed_mesh" for section in snapshot.section_names):
            return True
        return any("bed_mesh" in name.lower() for name in object_names)

    def is_input_shaper_configured(self, snapshot: ConfigSnapshot, object_names: list[str]) -> bool:
        if any(section.lower() == "input_shaper" for section in snapshot.section_names):
            return True
        return any("input_shaper" in name.lower() for name in object_names)

    def detect_camera_stack(self, addons: list[DetectedAddon], services: list[str]) -> str:
        addon_names = {addon.name.lower() for addon in addons}
        service_names = {service.lower() for service in services}
        if "crowsnest" in addon_names or "crowsnest" in service_names:
            return "crowsnest"
        return "none"
