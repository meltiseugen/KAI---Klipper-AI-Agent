"""Inspect parsed G-code metadata without opening files or starting a print."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from pydantic import Field, StrictStr, validator

from klipperai_agent.agent.ports import FileMetadataReader
from klipperai_agent.agent.tools.base import Tool, ToolArguments, ToolContext
from klipperai_agent.domain.evidence import SourceCitation
from klipperai_agent.domain.moonraker import gcode_filename


class FileMetadataArguments(ToolArguments):
    filename: StrictStr | None = Field(default=None, max_length=512)

    @validator("filename")
    def relative_filename(cls, value: str | None) -> str | None:
        return gcode_filename(value) if value is not None else None


class FileMetadataTool(Tool[FileMetadataArguments]):
    name = "get_gcode_metadata"
    label = "Read G-code file metadata"
    description = "Read Moonraker's parsed slicer, layer, filament and time metadata for a relative G-code filename, or the current job when filename is omitted. Does not read raw G-code or start printing. Estimates are not actual printer settings or completed-job measurements."
    arguments_type = FileMetadataArguments

    def __init__(self, reader: FileMetadataReader):
        self.reader = reader

    async def execute(
        self, arguments: FileMetadataArguments, context: ToolContext
    ) -> dict[str, Any]:
        filename = arguments.filename
        if filename is None:
            status = await context.moonraker.query_printer_objects({"print_stats": ["filename"]})
            stats = status.get("print_stats")
            filename = stats.get("filename") if isinstance(stats, dict) else None
            if not isinstance(filename, str) or not filename:
                return {
                    "error": "No current G-code filename is available. Supply a relative filename."
                }
        filename = gcode_filename(filename)
        metadata = await self.reader.get_file_metadata(filename)
        if not metadata:
            return {"error": "Moonraker has no supported metadata for this file."}
        context.moonraker_reachable = True
        context.citations.append(
            SourceCitation(
                label="Moonraker G-code metadata",
                path=f"gcodes/{filename}",
                excerpt=json.dumps(metadata, ensure_ascii=False),
            )
        )
        return {
            "filename": filename,
            "metadata": metadata,
            "observed_at": datetime.now(timezone.utc).isoformat(),
            "context_notes": "Parsed file metadata and slicer estimates, not raw G-code or proof of the printer's current configuration.",
        }
