"""Small local text retrieval with exact source excerpts and explicit version scope."""

from __future__ import annotations

import re
from heapq import nsmallest
from typing import Iterator

from klipperai_agent.domain.knowledge import CachedDocument


def search_documents(documents: list[CachedDocument], query: str, ids: set[str]) -> list[dict]:
    return nsmallest(
        3,
        _matches(documents, query, ids),
        key=lambda item: (-item["score"], item["document_id"], item["start_line"]),
    )


def _matches(documents: list[CachedDocument], query: str, ids: set[str]) -> Iterator[dict]:
    terms = set(re.findall(r"[a-z0-9_]{3,}", query.casefold()))
    for document in documents:
        if document.id not in ids or not document.content:
            continue
        lines = document.content.splitlines()
        ranges = (
            [
                (start, min(page.end_line, start + 32))
                for page in document.pages
                for start in range(page.start_line - 1, page.end_line, 24)
            ]
            if document.pages
            else [(start, start + 32) for start in range(0, len(lines), 24)]
        )
        for start, end in ranges:
            excerpt = "\n".join(lines[start:end])[:3500]
            normalized = excerpt.casefold()
            score = sum(normalized.count(term) for term in terms)
            if score:
                page = next(
                    (
                        page
                        for page in document.pages
                        if page.start_line <= start + 1 <= page.end_line
                    ),
                    None,
                )
                yield {
                    "document_id": document.id,
                    "title": document.title,
                    "url": document.url + (f"#page={page.page}" if page else ""),
                    "page": page.page if page else None,
                    "diagram_labels": page.diagram_labels if page else [],
                    "needs_visual_review": bool(page and page.needs_visual_review),
                    "firmware_commit": document.firmware_commit or None,
                    "digest": document.digest,
                    "fetched_at": document.fetched_at,
                    "start_line": start + 1,
                    "excerpt": excerpt,
                    "score": score,
                }
