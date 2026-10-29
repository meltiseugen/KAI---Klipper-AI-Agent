"""Validated public observations shared by model context, history and HTTP evidence."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from datetime import datetime, timezone
from typing import Any, Literal
from uuid import uuid4

from pydantic import Field

from klipperai_agent.domain.base import BaseModel
from klipperai_agent.domain.evidence import ArtifactInput, SourceCitation
from klipperai_agent.domain.redaction import redact_data, redact_text

ArtifactType = Literal[
    "klippy_log",
    "moonraker_log",
    "system_log",
    "config_snippet",
    "notes",
    "config_file",
    "printer_status",
    "printer_profile",
    "tool_result",
    "reference",
    "shutdown_report",
]
ArtifactOrigin = Literal[
    "user", "host", "moonraker", "config", "saved_profile", "tool", "web", "memory", "unknown"
]
Freshness = Literal[
    "current_snapshot", "historical", "saved_configuration", "user_supplied", "reference", "unknown"
]


class CollectedArtifact(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    kind: ArtifactType = "tool_result"
    label: str = Field(default="Collected evidence", max_length=120)
    source: str
    origin: ArtifactOrigin = "unknown"
    observed_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    freshness: Freshness = "unknown"
    status: Literal["complete", "partial", "unavailable"] = "complete"
    content: str = Field(max_length=16000)
    content_format: Literal["text", "json"] = "text"
    original_characters: int = Field(default=0, ge=0)
    line_basis: Literal["excerpt", "file", "none"] = "none"
    start_line: int | None = Field(default=None, ge=1)
    config_revision: str | None = None
    citations: list[SourceCitation] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)

    def prompt_metadata(self) -> dict[str, Any]:
        return self.model_dump(exclude={"content", "citations", "notes"}, exclude_none=True)

    def prompt_value(self) -> dict[str, Any]:
        return {
            "artifact": self.prompt_metadata(),
            "content": json.loads(self.content) if self.content_format == "json" else self.content,
        }


def normalize_artifact(
    *,
    source: str,
    content: str | dict[str, Any],
    kind: ArtifactType = "tool_result",
    label: str = "Collected evidence",
    origin: ArtifactOrigin = "unknown",
    freshness: Freshness = "unknown",
    observed_at: str | None = None,
    partial: bool = False,
    unavailable: bool = False,
    line_basis: Literal["excerpt", "file", "none"] = "none",
    start_line: int | None = None,
    config_revision: str | None = None,
    citations: list[SourceCitation] | None = None,
    notes: list[str] | None = None,
) -> CollectedArtifact:
    # Redact before hashing, clipping or handing any observation to a provider.
    text = (
        json.dumps(redact_data(content), ensure_ascii=False, allow_nan=False)
        if isinstance(content, dict)
        else redact_text(content)
    )
    stamp = observed_at or datetime.now(timezone.utc).isoformat()
    clipped = len(text) > 16000
    source = redact_text(source)[:500]
    identifier = hashlib.sha256(f"{source}|{kind}|{origin}|{stamp}|{text}".encode()).hexdigest()[
        :32
    ]
    return CollectedArtifact(
        id=identifier,
        kind=kind,
        label=redact_text(label)[:120],
        source=source,
        origin=origin,
        observed_at=stamp,
        freshness=freshness,
        status="unavailable" if unavailable else "partial" if partial or clipped else "complete",
        content=text[:15980] + "\n...[truncated]..." if clipped else text,
        content_format="json" if isinstance(content, dict) and not clipped else "text",
        original_characters=len(text),
        line_basis=line_basis,
        start_line=start_line,
        config_revision=config_revision,
        citations=[
            SourceCitation.parse_obj(
                redact_data(
                    {
                        **item.model_dump(),
                        "evidence_id": item.evidence_id or identifier,
                        "observed_at": item.observed_at or stamp,
                        "config_revision": item.config_revision or config_revision,
                        "line_basis": item.line_basis if item.line_basis != "none" else line_basis,
                    }
                )
            )
            for item in (citations or [])[:16]
        ],
        notes=[redact_text(note)[:500] for note in (notes or [])[:12]],
    )


def normalize_input(
    item: ArtifactInput, *, origin: ArtifactOrigin = "user", observed_at: str | None = None
) -> CollectedArtifact:
    return normalize_artifact(
        source=f"{origin}:{item.label}",
        label=item.label,
        kind=item.kind,
        content=item.content,
        origin=origin,
        observed_at=observed_at,
        freshness="user_supplied"
        if origin == "user"
        else "current_snapshot"
        if origin in {"host", "moonraker"}
        else "unknown",
        line_basis="excerpt",
        start_line=1,
        partial="...[truncated]..." in item.content,
        citations=[
            SourceCitation(
                label=item.label,
                path=f"{origin}:{item.label}",
                line_number=1,
                excerpt=redact_text(item.content)[:1000],
            )
        ],
        notes=[
            "Line numbers are within the collected excerpt. Collection time does not date every log event."
        ],
    )


def public_evidence_blocks(items: Sequence[CollectedArtifact]) -> list[CollectedArtifact]:
    """Bound the additive HTTP view while keeping IDs and collection timestamps."""
    blocks = []
    seen: set[str] = set()
    for item in items:
        if item.id in seen:
            continue
        seen.add(item.id)
        block = CollectedArtifact.parse_obj(redact_data(item.model_dump()))
        if len(block.content) > 2000:
            block.content = block.content[:1980] + "\n...[truncated]..."
            block.content_format = "text"
            if block.status != "unavailable":
                block.status = "partial"
            block.notes.append(
                "HTTP evidence excerpt clipped; additional collected content may exist."
            )
        block.citations = [
            citation.copy(
                update={
                    "excerpt": citation.excerpt[:500],
                    "label": citation.label[:120],
                    "path": citation.path[:1000],
                    "url": citation.url[:1000] if citation.url else None,
                }
            )
            for citation in block.citations[:4]
        ]
        block.source = block.source[:500]
        block.notes = [note[:500] for note in block.notes[:12]]
        blocks.append(block)
        if len(blocks) == 24:
            break
    return blocks
