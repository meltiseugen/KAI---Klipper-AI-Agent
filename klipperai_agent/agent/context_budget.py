"""Bound JSON evidence while retaining an explicit truncation marker."""

import json
from typing import Any


def fit_result(result: dict[str, Any], budget: int) -> dict[str, Any]:
    text = json.dumps(result)
    if len(text) <= budget:
        return result
    low, high = 0, len(text)
    while low < high:
        middle = (low + high + 1) // 2
        if len(json.dumps({"truncated": True, "excerpt": text[:middle]})) <= budget:
            low = middle
        else:
            high = middle - 1
    return {"truncated": True, "excerpt": text[:low]}
