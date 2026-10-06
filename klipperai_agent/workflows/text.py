from __future__ import annotations


def _looks_like_macro_target(target_text: str) -> bool:
    normalized = target_text.strip().strip("[]")
    lowered = normalized.lower()
    return lowered.startswith("gcode_macro ") or "_" in normalized or normalized.isupper()


def _dedupe_items(items: list[str] | tuple[str, ...] | object, *, limit: int) -> list[str]:
    if not isinstance(items, (list, tuple)):
        return []

    deduped: list[str] = []
    seen: set[str] = set()
    for item in items:
        normalized = str(item).strip()
        if not normalized:
            continue
        lowered = normalized.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        deduped.append(normalized)
        if len(deduped) >= limit:
            break
    return deduped
