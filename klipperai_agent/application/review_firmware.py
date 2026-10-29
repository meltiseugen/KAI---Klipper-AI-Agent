"""Bounded read-only version evidence, with saved identity explicitly labeled."""

from __future__ import annotations

import asyncio

from klipperai_agent.agent.ports import PrinterReader, SavedProfile
from klipperai_agent.domain.investigation import utc_now
from klipperai_agent.domain.proposals import ReviewFirmware
from klipperai_agent.domain.redaction import redact_text


async def read_review_firmware(
    printer: PrinterReader | None, profile: SavedProfile | None
) -> ReviewFirmware:
    saved = profile.to_summary() if profile is not None else {}
    firmware = ReviewFirmware(
        flavor=redact_text(str(saved.get("firmware_flavor") or ""))[:80],
        version=redact_text(str(saved.get("firmware_version") or ""))[:120],
        source="saved_profile" if saved else "unavailable",
        observed_at=utc_now(),
        note="Firmware identity is saved context, not proof of the currently installed fork or build.",
    )
    if printer is not None:
        try:
            info = await asyncio.wait_for(printer.get_printer_info(), timeout=5)
            version = info.get("software_version")
            if not isinstance(version, str) or not version.strip():
                raise ValueError("Version unavailable.")
            firmware.version = redact_text(version.strip())[:120]
            firmware.source = "live_version_saved_flavor"
            firmware.note = "Version read from Moonraker /printer/info; fork identity still comes from the saved profile. Confirm both before editing."
        except Exception:
            # Never persist exception text, filesystem paths or transport credentials.
            firmware.note = "Live firmware version unavailable; any displayed identity/version is saved context and must be checked manually."
    return firmware
