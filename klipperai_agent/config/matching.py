from __future__ import annotations

import re

from klipperai_agent.config.vocabulary import _FEATURE_SECTION_PREFIXES, ConfigFeature


def _normalize_section_lookup_key(section_name: str) -> str:
    return re.sub(r"[\s-]+", "_", section_name.strip().lower())


def _infer_feature_from_section_name(section_name: str) -> ConfigFeature:
    lowered = section_name.lower()
    for feature, prefixes in _FEATURE_SECTION_PREFIXES.items():
        if any(_section_matches_prefix(lowered, prefix) for prefix in prefixes):
            return feature
    return "generic"


def _section_matches_prefix(section_name: str, prefix: str) -> bool:
    lowered_section = section_name.lower()
    lowered_prefix = prefix.lower()
    if lowered_prefix.endswith("_"):
        return lowered_section.startswith(lowered_prefix)
    if lowered_section == lowered_prefix:
        return True
    if not lowered_section.startswith(lowered_prefix):
        return False
    next_char = lowered_section[len(lowered_prefix) : len(lowered_prefix) + 1]
    return next_char in {"", " ", "_"} or next_char.isdigit()


def _inline_code(value: str) -> str:
    return value.replace("`", "'")
