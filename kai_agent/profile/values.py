from __future__ import annotations

from typing import Any


def _string(value: Any) -> str | None:
    if value is None:
        return None
    stringified = str(value).strip()
    return stringified or None


def _first_non_empty(*values: str | None) -> str | None:
    for value in values:
        if value:
            return value
    return None
