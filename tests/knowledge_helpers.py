"""Synthetic hardware evidence; never a production board catalog."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

from klipperai_agent.config.models import ConfigDocument, ConfigSnapshot
from klipperai_agent.config.parser import ConfigParser
from klipperai_agent.domain.knowledge import (
    CachedDocument,
    ComponentIdentity,
    FanMapping,
    KnowledgeSetup,
)
from klipperai_agent.knowledge.sources import component_key, document_source, mapping_evidence


def identities():
    return [
        ComponentIdentity(
            role="mainboard",
            model="Example Board A",
            revision="1.0",
            mcu="mcu",
            connection="USB",
            confirmed=True,
        ),
        ComponentIdentity(
            role="toolhead",
            model="Example Board B",
            revision="1.3",
            mcu="th",
            connection="CAN",
            confirmed=True,
        ),
        ComponentIdentity(
            role="probe",
            category="probe",
            model="Example Eddy Probe",
            mcu="eddy",
            connection="USB",
            confirmed=True,
        ),
    ]


def setup():
    components = identities()
    return KnowledgeSetup(
        components=components,
        firmware_flavor="Klipper",
        firmware_version="v0.13.0",
        facts="Fan0 is a 24V part cooling fan.",
        reviewed_fan_mappings={
            item.role: mapping_evidence(item, documents())["signature"] for item in components
        },
    )


def documents():
    result = []
    for component, pins in zip(
        identities(), [("PA8", "PB15", "PB14"), ("PA9", "PB15", "PA6", "PA5"), ()]
    ):
        mappings = [
            FanMapping(
                connector=f"FAN{index}",
                pin=pin,
                quote=f"FAN{index} pin {pin}",
                electrical="Verify voltage jumper before wiring.",
            )
            for index, pin in enumerate(pins)
        ]
        content = (
            "Reference\ncalibration thermal drift homing\nFan connector and supply voltage\n"
            + "\n".join(item.quote for item in mappings)
        )
        result.append(
            CachedDocument(
                id=component.role + "-guide",
                title=component.model + " reference",
                url="https://example.org/" + component.role,
                kind="text",
                digest="a" * 64,
                fetched_at="2026-10-16T10:00:00+00:00",
                content=content,
                component_key=component_key(component),
                fan_mappings=mappings,
            )
        )
    result[-1].id = "eddy-guide"
    result.append(result[-1].copy(update={"id": "klipper-eddy", "title": "Firmware probe guide"}))
    return result


def researcher():
    async def discover(component, data):
        return [
            document_source(component, "https://example.org/" + component.role, component.model)
        ]

    return SimpleNamespace(
        discover=AsyncMock(side_effect=discover), extract=AsyncMock(return_value=[])
    )


def snapshot(text="", *, notes=None, truncated=False):
    content = (
        "[mcu]\nserial: /dev/serial/by-id/main\n[mcu th]\ncanbus_uuid: abcdef\n[mcu eddy]\nserial: /dev/serial/by-id/eddy\n"
        + text
    )
    return ConfigSnapshot(
        "printer.cfg",
        [
            ConfigDocument(
                "printer.cfg", content, ConfigParser.extract_sections(content), truncated=truncated
            )
        ],
        notes=notes or [],
    )
