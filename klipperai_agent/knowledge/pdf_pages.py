"""Page and diagram locators from a bounded PDF text index."""

import re

from klipperai_agent.domain.hardware import PdfPageIndex


def pdf_pages(text: str) -> list[PdfPageIndex]:
    pattern = r"^\[PDF page (\d+); images=(\d+); vector_paths=(\d+); visual_review_required\]$"
    lines = text.splitlines()
    headers = [
        (index, re.fullmatch(pattern, line))
        for index, line in enumerate(lines)
        if re.fullmatch(pattern, line)
    ]
    result = []
    for position, (start, match) in enumerate(headers):
        assert match is not None
        end = headers[position + 1][0] if position + 1 < len(headers) else len(lines)
        body = "\n".join(lines[start + 1 : end]).strip()
        labels = [
            line[:200]
            for line in body.splitlines()
            if re.search(r"\b(fig(?:ure)?|diagram|schematic|pinout|connector)\b", line, re.I)
        ][:32]
        result.append(
            PdfPageIndex(
                page=int(match[1]),
                start_line=start + 1,
                end_line=end,
                text=body[:24000],
                images=int(match[2]),
                vector_paths=int(match[3]),
                diagram_labels=labels,
            )
        )
    return result
