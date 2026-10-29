"""Parse public PDFs in a bounded child process; no scripts, attachments or URLs run."""

from __future__ import annotations

import io
import json
import subprocess
import sys


def parse_pdf(original: bytes) -> str:
    from pypdf import PdfReader, filters

    filters.ZLIB_MAX_OUTPUT_LENGTH = 2_000_000
    reader = PdfReader(io.BytesIO(original), strict=True)
    if reader.is_encrypted or len(reader.pages) > 80:
        raise ValueError("Encrypted or oversized PDF cannot be indexed.")
    parts = []
    total = 0
    for number, page in enumerate(reader.pages, 1):
        stream = page.get_contents()
        if stream is not None and len(stream.get_data()) > 2_000_000:
            raise ValueError("PDF page content exceeds indexing budget.")
        counts = {"images": 0, "paths": 0}

        def operator(op, args, cm, tm):
            if op in {b"Do", b"INLINE IMAGE"}:
                counts["images"] += 1
            if op in {b"m", b"l", b"re", b"c"}:
                counts["paths"] += 1

        text = (page.extract_text(visitor_operand_before=operator) or "").strip()
        if len(text) > 24000:
            raise ValueError("PDF page text exceeds indexing budget.")
        heading = f"[PDF page {number}; images={counts['images']}; vector_paths={counts['paths']}; visual_review_required]\n"
        body = (
            text
            or "[No readable text; inspect this page visually or add a confirmed diagram note.]"
        )
        parts.append(heading + body)
        total += len(parts[-1])
        if total > 280000:
            raise ValueError("PDF text exceeds indexing budget.")
    return "\n\n".join(parts)


def index_pdf(original: bytes) -> str:
    if len(original) > 8 * 1024 * 1024:
        raise ValueError("PDF exceeds download budget.")
    try:
        result = subprocess.run(
            [sys.executable, "-m", "klipperai_agent.infrastructure.pdf_index"],
            input=original,
            capture_output=True,
            timeout=12,
            check=False,
        )
        if result.returncode or len(result.stdout) > 1_000_000:
            raise ValueError("PDF indexing is unavailable or exceeded its budget.")
        text = json.loads(result.stdout)["text"]
        if not isinstance(text, str) or len(text) > 300000:
            raise ValueError("Invalid PDF index.")
        return text
    except (subprocess.TimeoutExpired, OSError, KeyError, ValueError) as exc:
        raise ValueError("PDF indexing failed; retain the original for manual review.") from exc


def main() -> None:
    # Linux hosts also cap the entire parser's address space; Windows retains the
    # child-process deadline, stream/page limits and input/output bounds.
    if sys.platform == "linux":
        import resource

        resource.setrlimit(resource.RLIMIT_AS, (384 * 1024 * 1024, 384 * 1024 * 1024))
    original = sys.stdin.buffer.read(8 * 1024 * 1024 + 1)
    if len(original) > 8 * 1024 * 1024:
        raise ValueError("PDF exceeds download budget.")
    sys.stdout.write(json.dumps({"text": parse_pdf(original)}))


if __name__ == "__main__":
    main()
