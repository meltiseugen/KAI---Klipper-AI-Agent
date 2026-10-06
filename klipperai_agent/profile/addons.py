from __future__ import annotations

from typing import Any

from klipperai_agent.config.models import ConfigSnapshot
from klipperai_agent.profile.models import (
    DetectedAddon,
    ProfileConfidence,
)


class AddonDetector:
    _ADDON_SIGNATURES: tuple[tuple[str, tuple[str, ...]], ...] = (
        ("Beacon", ("beacon",)),
        ("Eddy", ("probe_eddy_current", "eddy")),
        ("Cartographer", ("cartographer",)),
        ("Klicky", ("klicky", "dockable_probe")),
        ("KAMP", ("klipper-adaptive-meshing-purging", "adaptive_mesh", "line_purge", "smart_park")),
        ("OctoEverywhere", ("octoeverywhere",)),
        ("Crowsnest", ("crowsnest",)),
        ("Sonar", ("sonar",)),
        ("Moonraker Timelapse", ("moonraker-timelapse", "timelapse")),
        ("KlipperScreen", ("klipperscreen",)),
    )

    def detect_addons(
        self,
        snapshot: ConfigSnapshot,
        object_names: list[str],
        update_status: Any,
        services: list[str],
    ) -> list[DetectedAddon]:
        config_paths = [document.path.lower() for document in snapshot.documents]
        config_sections = [section.lower() for section in snapshot.section_names]
        object_haystack = [name.lower() for name in object_names]
        update_haystack: list[str] = []
        if isinstance(update_status, dict):
            version_info = update_status.get("version_info")
            if isinstance(version_info, dict):
                update_haystack.extend(str(key).lower() for key in version_info)
                update_haystack.extend(str(value).lower() for value in version_info.values())
        service_haystack = [service.lower() for service in services]

        detected: list[DetectedAddon] = []
        seen: set[str] = set()
        for addon_name, keywords in self._ADDON_SIGNATURES:
            source = None
            confidence: ProfileConfidence = "medium"
            detail = None
            if any(keyword in item for item in update_haystack for keyword in keywords):
                source = "Moonraker update manager"
                confidence = "high"
            elif any(keyword in item for item in object_haystack for keyword in keywords):
                source = "Loaded printer objects"
                confidence = "high"
            elif any(keyword in item for item in service_haystack for keyword in keywords):
                source = "Moonraker monitored services"
                confidence = "high"
            elif any(keyword in item for item in config_sections for keyword in keywords):
                source = "Klipper config sections"
                confidence = "medium"
            elif any(keyword in item for item in config_paths for keyword in keywords):
                source = "Klipper include paths"
                confidence = "medium"
            if not source:
                continue
            lowered_name = addon_name.lower()
            if lowered_name in seen:
                continue
            seen.add(lowered_name)
            if source == "Loaded printer objects":
                matching = next(
                    (
                        item
                        for item in object_haystack
                        if any(keyword in item for keyword in keywords)
                    ),
                    None,
                )
                detail = matching
            detected.append(
                DetectedAddon(
                    name=addon_name,
                    source=source,
                    confidence=confidence,
                    detail=detail,
                )
            )

        detected.sort(
            key=lambda item: ({"high": 2, "medium": 1, "low": 0}[item.confidence], item.name),
            reverse=True,
        )
        return detected
