"""Small local text retrieval with exact source excerpts and explicit version scope."""

from __future__ import annotations

import re

from klipperai_agent.domain.knowledge import CachedDocument


def search_documents(documents: list[CachedDocument], query: str, ids: set[str]) -> list[dict]:
    terms = set(re.findall(r"[a-z0-9_]{3,}", query.casefold()))
    matches: list[dict] = []
    for document in documents:
        if document.id not in ids or not document.content:
            continue
        lines = document.content.splitlines()
        for start in range(0, len(lines), 24):
            excerpt = "\n".join(lines[start : start + 32])[:3500]
            score = sum(excerpt.casefold().count(term) for term in terms)
            if score:
                matches.append(
                    {
                        "document_id": document.id,
                        "title": document.title,
                        "url": document.url,
                        "digest": document.digest,
                        "fetched_at": document.fetched_at,
                        "start_line": start + 1,
                        "excerpt": excerpt,
                        "score": score,
                    }
                )
    return sorted(
        matches, key=lambda item: (-item["score"], item["document_id"], item["start_line"])
    )[:3]
