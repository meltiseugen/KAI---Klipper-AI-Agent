from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from klipperai_agent.config.models import ConfigDocument, ConfigSnapshot
from klipperai_agent.profile.values import _string


class HardwareDetector:
    _BOARD_HINTS: tuple[tuple[str, tuple[str, ...]], ...] = (
        ("BTT Octopus Pro", ("octopus pro",)),
        ("BTT Octopus", ("octopus",)),
        ("BTT Manta M8P", ("manta m8p",)),
        ("BTT Manta M5P", ("manta m5p",)),
        ("BTT SKR Mini E3", ("skr mini e3",)),
        ("BTT SKR Pico", ("skr pico",)),
        ("BTT SKR 3", ("skr 3",)),
        ("BTT Spider", ("spider",)),
        ("Mellow Fly", ("mellow fly", "fly-", "fly ")),
        ("Fysetc Spider", ("fysetc spider",)),
    )

    _TOOLHEAD_BOARD_HINTS: tuple[tuple[str, tuple[str, ...]], ...] = (
        ("BTT EBB36", ("ebb36",)),
        ("BTT EBB42", ("ebb42",)),
        ("Mellow SB2209", ("sb2209",)),
        ("Mellow SB2240", ("sb2240",)),
    )

    _TOOLHEAD_HINTS: tuple[tuple[str, tuple[str, ...]], ...] = (
        ("Stealthburner", ("stealthburner",)),
        ("Afterburner", ("afterburner",)),
        ("Dragon Burner", ("dragonburner", "dragon burner")),
        ("Orbiter", ("orbiter",)),
        ("Hermit Crab", ("hermitcrab", "hermit crab")),
        ("EVA", ("eva toolhead", "eva-")),
    )

    @staticmethod
    def extract_mcu_sections(parsed: list[dict[str, Any]]) -> list[dict[str, Any]]:
        sections: list[dict[str, Any]] = []
        for entry in parsed:
            section = str(entry.get("section", "")).strip()
            lowered = section.lower()
            if not lowered.startswith("mcu"):
                continue
            alias = section[3:].strip() if lowered != "mcu" else "mcu"
            sections.append(
                {
                    "name": alias,
                    "section": section,
                    "options": entry.get("options", {}),
                    "path": entry.get("path"),
                }
            )
        return sections

    @staticmethod
    def select_primary_mcu(mcu_sections: list[dict[str, Any]]) -> dict[str, Any] | None:
        for entry in mcu_sections:
            if str(entry.get("name", "")).lower() == "mcu":
                return entry
        return mcu_sections[0] if mcu_sections else None

    @staticmethod
    def select_toolhead_mcu(mcu_sections: list[dict[str, Any]]) -> dict[str, Any] | None:
        for entry in mcu_sections:
            name = str(entry.get("name", "")).lower()
            options = entry.get("options", {})
            if name == "mcu" or name == "linux":
                continue
            if any(token in name for token in ("toolhead", "ebb", "sb", "head")):
                return entry
            if isinstance(options, dict) and options.get("canbus_uuid"):
                return entry
        return None

    def describe_mcu(
        self,
        mcu_section: dict[str, Any] | None,
        serial_devices: list[dict[str, Any]],
        usb_devices: list[dict[str, Any]],
    ) -> str | None:
        if not mcu_section:
            return None

        options = mcu_section.get("options", {})
        if not isinstance(options, dict):
            return None

        serial_value = _string(options.get("serial"))
        if serial_value:
            matched_serial = self._match_serial_device(serial_value, serial_devices)
            if matched_serial:
                usb_location = _string(matched_serial.get("usb_location"))
                matched_usb = self._match_usb_device(usb_location, usb_devices)
                if matched_usb:
                    manufacturer = _string(matched_usb.get("manufacturer"))
                    product = _string(matched_usb.get("product"))
                    if manufacturer and product and manufacturer.lower() not in product.lower():
                        return f"{manufacturer} {product}"
                    return product or manufacturer
                device_name = _string(matched_serial.get("path_by_id")) or _string(
                    matched_serial.get("device_name")
                )
                if device_name:
                    return device_name
            return self._extract_mcu_token(serial_value)

        canbus_uuid = _string(options.get("canbus_uuid"))
        if canbus_uuid:
            return f"CAN UUID {canbus_uuid[:12]}"
        return None

    def detect_toolhead_board(
        self,
        toolhead_mcu: dict[str, Any] | None,
        serial_devices: list[dict[str, Any]],
        usb_devices: list[dict[str, Any]],
        snapshot: ConfigSnapshot,
    ) -> str | None:
        explicit = self._match_named_hint(
            self._TOOLHEAD_BOARD_HINTS + self._BOARD_HINTS,
            snapshot,
            None,
            toolhead_mcu,
            documents_override=self._select_toolhead_documents(snapshot),
        )
        if explicit:
            return explicit
        description = self.describe_mcu(toolhead_mcu, serial_devices, usb_devices)
        if not toolhead_mcu:
            return None
        alias = str(toolhead_mcu.get("name", "")).strip()
        if description and alias and alias.lower() != "mcu":
            return f"{alias} ({description})"
        return description

    def detect_mainboard(
        self,
        snapshot: ConfigSnapshot,
        primary_mcu: dict[str, Any] | None,
    ) -> str | None:
        target_path = _string(primary_mcu.get("path")) if primary_mcu else None
        return self._match_named_hint(
            self._BOARD_HINTS,
            snapshot,
            primary_mcu,
            None,
            path_filter=target_path,
        )

    def detect_toolhead(
        self,
        snapshot: ConfigSnapshot,
        toolhead_mcu: dict[str, Any] | None,
    ) -> str | None:
        target_path = _string(toolhead_mcu.get("path")) if toolhead_mcu else None
        scoped = self._match_named_hint(
            self._TOOLHEAD_HINTS,
            snapshot,
            None,
            toolhead_mcu,
            path_filter=target_path,
        )
        if scoped:
            return scoped
        return self._match_named_hint(
            self._TOOLHEAD_HINTS,
            snapshot,
            None,
            toolhead_mcu,
            documents_override=self._select_toolhead_documents(snapshot),
        )

    @staticmethod
    def _select_toolhead_documents(snapshot: ConfigSnapshot) -> list[ConfigDocument]:
        keywords = (
            "toolhead",
            "ebb",
            "sb",
            "stealthburner",
            "afterburner",
            "dragonburner",
            "orbiter",
            "canbus",
        )
        matched = [
            document
            for document in snapshot.documents
            if any(
                keyword in document.path.lower() or keyword in document.content.lower()
                for keyword in keywords
            )
        ]
        return matched or snapshot.documents

    @staticmethod
    def _match_serial_device(
        serial_value: str, serial_devices: list[dict[str, Any]]
    ) -> dict[str, Any] | None:
        for device in serial_devices:
            for key in ("path_by_id", "path_by_hardware", "device_path"):
                candidate = device.get(key)
                if isinstance(candidate, str) and candidate == serial_value:
                    return device
        return None

    @staticmethod
    def _match_usb_device(
        usb_location: str | None, usb_devices: list[dict[str, Any]]
    ) -> dict[str, Any] | None:
        if not usb_location:
            return None
        for device in usb_devices:
            if str(device.get("usb_location", "")).strip() == usb_location:
                return device
        return None

    @staticmethod
    def _extract_mcu_token(value: str) -> str:
        match = re.search(r"usb-[^-_]+[_-]([A-Za-z0-9]+)", value)
        if match:
            return match.group(1)
        if "/dev/" not in value:
            return value
        return Path(value).name

    def _match_named_hint(
        self,
        catalog: tuple[tuple[str, tuple[str, ...]], ...],
        snapshot: ConfigSnapshot,
        primary_mcu: dict[str, Any] | None,
        extra_mcu: dict[str, Any] | None,
        *,
        documents_override: list[ConfigDocument] | None = None,
        path_filter: str | None = None,
    ) -> str | None:
        documents = documents_override or snapshot.documents
        if path_filter:
            filtered = [document for document in documents if document.path == path_filter]
            if filtered:
                documents = filtered
        haystacks: list[str] = [document.path.lower() for document in documents]
        haystacks.extend(document.content.lower() for document in documents)
        if primary_mcu:
            haystacks.append(str(primary_mcu).lower())
        if extra_mcu:
            haystacks.append(str(extra_mcu).lower())
        for label, keywords in catalog:
            if any(keyword in haystack for haystack in haystacks for keyword in keywords):
                return label
        return None
