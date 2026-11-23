"""Validate user-grounded memory proposals before application-owned persistence."""

import re
from uuid import uuid4

from kai_agent.domain.investigation import ConfirmedMemory
from kai_agent.domain.memory import MemoryProposal, MemoryUpdate
from kai_agent.domain.redaction import redact_text


def explicit_memory_request(message: str) -> bool:
    return bool(re.search(
        r"\b(remember|forget|memor(?:y|ies)|actually|update|correct)\b|keep (?:this|that|it) in mind|"
        r"\b(?:update|correct|change)\b.{0,60}\b(?:that|this|it)\b", message, re.I,
    ))


def forget_requested(message: str) -> bool:
    return bool(
        re.search(r"\bforget\b|\b(?:delete|remove)\b.{0,60}\bmemor(?:y|ies)\b", message, re.I)
        and not re.search(r"\b(?:don't|do not|never)\s+forget\b", message, re.I)
    )


def memory_catalog(entries: list[ConfirmedMemory]) -> list[dict]:
    result: list[dict] = []
    remaining = 12000
    for item in entries[:100]:
        content = item.content[:400]
        if len(content) > remaining:
            break
        result.append({
            "id": item.id, "kind": item.kind, "content": content,
            "saved_at": item.confirmed_at,
        })
        remaining -= len(content) + len(item.id) + 50
    return result


def prepare_memory_updates(
    proposals: list[MemoryProposal],
    message: str,
    entries: list[ConfirmedMemory],
    thread_id: str,
    *,
    automatic: bool,
) -> tuple[list[MemoryUpdate], str]:
    requested = explicit_memory_request(message)
    if not automatic and not requested:
        return [], ""
    existing = {entry.id: entry for entry in entries}
    normalized = {" ".join(entry.content.casefold().split()) for entry in entries}
    changes: list[MemoryUpdate] = []
    touched: set[str] = set()
    rejected = False
    forgetting = forget_requested(message)
    for proposal in proposals[:3]:
        quote = proposal.source_quote.strip()
        content = redact_text(proposal.content.strip())
        old = existing.get(proposal.memory_id)
        if (
            not quote
            or quote not in message
            or len(quote) < min(8, len(message.strip()))
            or redact_text(quote) != quote
            or (proposal.action != "add" and (old is None or old.id in touched))
            or (proposal.action == "add" and proposal.memory_id)
            or (proposal.action == "forget" and not forgetting)
            or (
                proposal.action != "forget"
                and (not content or content != proposal.content.strip() or forgetting)
            )
        ):
            rejected = True
            continue
        key = " ".join(content.casefold().split())
        if proposal.action == "add" and key in normalized:
            continue
        if proposal.action == "update" and old and key == " ".join(old.content.casefold().split()):
            continue
        identity = old.id if old else str(uuid4())
        changes.append(MemoryUpdate(
            id=identity, action=proposal.action,
            kind=old.kind if proposal.action == "forget" and old else proposal.kind,
            content=old.content if proposal.action == "forget" and old else content,
            before_content=old.content if old else "",
            expected_revision=old.revision if old else 0,
            origin="requested" if requested else "automatic", source_quote=quote,
            source_chat_id=thread_id,
        ))
        touched.add(identity)
        normalized.add(key)
    error = (
        "Some memory changes could not be saved. Open Printer memory to review them."
        if rejected else ""
    )
    return changes, error
