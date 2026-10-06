from __future__ import annotations

import json
from typing import Any, get_args

from klipperai_agent.config.vocabulary import ConfigFeature

_CONFIG_FEATURE_VALUES = tuple(get_args(ConfigFeature))


_CONFIG_FEATURE_SET = frozenset(_CONFIG_FEATURE_VALUES)


_CONFIG_FEATURE_ALIASES = {
    "config": "generic",
    "config_file": "generic",
    "include": "generic",
    "include_file": "generic",
}


def _parse_json_object(value: str) -> dict[str, Any]:
    normalized = value.strip()
    if normalized.startswith("```"):
        lines = normalized.splitlines()
        if lines:
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        normalized = "\n".join(lines).strip()

    parsed = json.loads(normalized or "{}")
    if not isinstance(parsed, dict):
        raise ValueError("OpenAI response was not a JSON object.")
    return parsed


def _with_required_summary(data: dict[str, Any], fallback: str) -> dict[str, Any]:
    if not str(data.get("summary", "")).strip():
        data = {**data, "summary": fallback}
    return data


def _normalize_config_assistant_data(
    data: dict[str, Any],
    *,
    fallback_feature: ConfigFeature,
) -> dict[str, Any]:
    proposals = data.get("proposals")
    if isinstance(proposals, dict):
        proposals = [proposals]
    if not isinstance(proposals, list):
        return data

    normalized_proposals: list[Any] = []
    for item in proposals:
        if not isinstance(item, dict):
            normalized_proposals.append(item)
            continue

        raw_feature = str(item.get("feature") or "").strip().lower()
        normalized_feature = raw_feature.replace("-", "_").replace(" ", "_")
        normalized_feature = _CONFIG_FEATURE_ALIASES.get(normalized_feature, normalized_feature)
        if normalized_feature not in _CONFIG_FEATURE_SET:
            normalized_feature = fallback_feature
        normalized_proposals.append({**item, "feature": normalized_feature})

    return {**data, "proposals": normalized_proposals}


def _coerce_string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if not isinstance(value, (list, tuple)):
        text = _stringify_llm_item(value)
        return [text] if text else []

    items: list[str] = []
    for item in value:
        text = _stringify_llm_item(item)
        if text:
            items.append(text)
    return items


def _stringify_llm_item(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        for key in (
            "summary",
            "text",
            "message",
            "cause",
            "action",
            "question",
            "description",
            "value",
        ):
            nested = value.get(key)
            text = _stringify_llm_item(nested)
            if text:
                return text
        scalar_parts = [
            f"{key}: {nested}"
            for key, nested in value.items()
            if isinstance(nested, (str, int, float, bool)) and str(nested).strip()
        ]
        if scalar_parts:
            return "; ".join(scalar_parts)
        try:
            return json.dumps(value, sort_keys=True)
        except TypeError:
            return str(value)
    if isinstance(value, (list, tuple)):
        return "; ".join(item for item in (_stringify_llm_item(item) for item in value) if item)
    return str(value).strip()
