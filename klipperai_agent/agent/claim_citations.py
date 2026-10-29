"""Resolve model references against observations; the application owns source details."""

from klipperai_agent.agent.response_contracts import CitedClaim
from klipperai_agent.domain.evidence import GroundedClaim, SourceCitation
from klipperai_agent.domain.investigation import Evidence


def resolve_claims(claims: list[CitedClaim], evidence: list[Evidence]) -> list[GroundedClaim]:
    by_id = {item.id: item for item in evidence}
    result = []
    for claim in claims:
        citations: list[SourceCitation] = []
        for reference in claim.evidence_refs:
            item = by_id.get(reference.evidence_id)
            if item is None or item.status == "unavailable":
                raise ValueError("Unknown or unavailable evidence reference.")
            start, end = reference.start_line, reference.end_line
            if start == end == 0:
                if not item.citations:
                    raise ValueError(
                        "This observation has no source citations; read its source first."
                    )
                citations.extend(
                    citation.copy(
                        update={
                            "evidence_id": item.id,
                            "observed_at": item.observed_at,
                            "config_revision": item.config_revision,
                        }
                    )
                    for citation in item.citations[:4]
                )
                continue
            if item.line_basis == "none" or item.content_format != "text":
                raise ValueError("This observation has no citable text lines.")
            lines = item.content.splitlines()
            offset = item.start_line or 1
            first, last = start - offset, end - offset
            if first < 0 or last < first or last >= len(lines) or end - start >= 120:
                raise ValueError("Citation range is outside the retained source or too large.")
            excerpt = "\n".join(lines[first : last + 1])
            if "...[truncated]..." in excerpt or len(excerpt) > 4000:
                raise ValueError(
                    "Citation includes clipped evidence; request a narrower source read."
                )
            section = None
            if item.line_basis == "file":
                for raw in lines[: first + 1]:
                    if raw.strip().startswith("[") and "]" in raw:
                        section = raw.strip()[1:].split("]", 1)[0].strip()
            citations.append(
                SourceCitation(
                    label=item.label,
                    path=item.citations[0].path if item.citations else item.source,
                    line_number=start,
                    end_line=end,
                    section=section,
                    excerpt=excerpt,
                    line_basis=item.line_basis,
                    evidence_id=item.id,
                    observed_at=item.observed_at,
                    config_revision=item.config_revision,
                )
            )
        result.append(GroundedClaim(claim=claim.claim, citations=citations))
    return result
