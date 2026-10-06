from __future__ import annotations

import re

from klipperai_agent.config.macro_names import (
    _extract_explicit_section_name,
    _extract_macro_section_name,
)
from klipperai_agent.config.matching import _infer_feature_from_section_name
from klipperai_agent.config.models import ConfigRequestTarget
from klipperai_agent.config.vocabulary import (
    _EDIT_INTENT_WORDS,
    _EXPLAIN_INTENT_WORDS,
    _FEATURE_KEYWORDS,
    _LOOKUP_CORRECTION_WORDS,
    ConfigRequestIntent,
)


def infer_config_request_target(message: str) -> ConfigRequestTarget:
    lowered = message.lower()

    explicit_section = _extract_explicit_section_name(message)
    if explicit_section:
        feature = _infer_feature_from_section_name(explicit_section)
        if _looks_like_edit_request(lowered):
            intent: ConfigRequestIntent = "edit"
        elif _looks_like_explain_request(lowered):
            intent = "explain"
        else:
            intent = "locate"
        return ConfigRequestTarget(
            feature=feature,
            rationale=f"Matched explicit section lookup for [{explicit_section}].",
            intent=intent,
            section_name=explicit_section,
        )

    macro_section = _extract_macro_section_name(message)
    if macro_section and _looks_like_edit_request(lowered):
        return ConfigRequestTarget(
            feature="macro",
            rationale=f"Matched macro edit request for [{macro_section}].",
            intent="edit",
            section_name=macro_section,
        )

    if macro_section and (
        _looks_like_lookup_request(lowered) or _looks_like_lookup_correction(lowered)
    ):
        return ConfigRequestTarget(
            feature="macro",
            rationale=f"Matched macro lookup for [{macro_section}].",
            intent="locate",
            section_name=macro_section,
        )

    if macro_section and _looks_like_explain_request(lowered):
        return ConfigRequestTarget(
            feature="macro",
            rationale=f"Matched macro explanation request for [{macro_section}].",
            intent="explain",
            section_name=macro_section,
        )

    for feature, keywords in _FEATURE_KEYWORDS:
        if any(keyword in lowered for keyword in keywords):
            if _looks_like_lookup_request(lowered):
                intent = "locate"
            elif _looks_like_edit_request(lowered):
                intent = "edit"
            elif _looks_like_explain_request(lowered):
                intent = "explain"
            else:
                intent = "generate"
            return ConfigRequestTarget(
                feature=feature,
                rationale=f"Matched request keywords for {feature}.",
                intent=intent,
            )

    return ConfigRequestTarget(
        feature="generic",
        rationale="No specific supported config feature was detected from the request text.",
    )


def looks_like_config_request(message: str) -> bool:
    lowered = message.lower()
    generate_intent_words = (
        "add",
        "generate",
        "create",
        "write",
        "make",
        "build",
        "draft",
        "propose",
        "configure",
        "config",
        "cfg",
        "setup",
        "set up",
        "change",
        "define",
        "disable",
        "edit",
        "enable",
        "improve",
        "modify",
        "optimize",
        "remove",
        "rename",
        "replace",
        "rewrite",
        "turn off",
        "turn on",
        "update",
    )
    lookup_intent_words = (
        "where",
        "which file",
        "what file",
        "find",
        "locate",
        "show me where",
        "defined",
        "configured",
        "declared",
    )
    if _extract_explicit_section_name(message):
        return True

    has_generate_intent = any(word in lowered for word in generate_intent_words)
    has_lookup_intent = any(
        word in lowered for word in lookup_intent_words
    ) or _looks_like_section_content_request(lowered)
    if _extract_macro_section_name(message) and (
        has_lookup_intent
        or _looks_like_lookup_correction(lowered)
        or _looks_like_explain_request(lowered)
        or _looks_like_edit_request(lowered)
    ):
        return True

    has_feature = any(
        keyword in lowered for _, keywords in _FEATURE_KEYWORDS for keyword in keywords
    )
    return has_feature and (
        has_generate_intent or has_lookup_intent or _looks_like_explain_request(lowered)
    )


def _looks_like_lookup_request(lowered_message: str) -> bool:
    lookup_intent_words = (
        "where",
        "which file",
        "what file",
        "find",
        "locate",
        "show me where",
        "defined",
        "configured",
        "declared",
    )
    return any(
        word in lowered_message for word in lookup_intent_words
    ) or _looks_like_section_content_request(lowered_message)


def _looks_like_lookup_correction(lowered_message: str) -> bool:
    return any(word in lowered_message for word in _LOOKUP_CORRECTION_WORDS)


def _looks_like_explain_request(lowered_message: str) -> bool:
    return any(word in lowered_message for word in _EXPLAIN_INTENT_WORDS)


def _looks_like_edit_request(lowered_message: str) -> bool:
    return any(_contains_intent_phrase(lowered_message, word) for word in _EDIT_INTENT_WORDS)


def _contains_intent_phrase(lowered_message: str, phrase: str) -> bool:
    pattern = r"(?<![a-z0-9_])" + re.escape(phrase).replace(r"\ ", r"\s+") + r"(?![a-z0-9_])"
    return bool(re.search(pattern, lowered_message))


def looks_like_config_content_request(message: str) -> bool:
    return _looks_like_section_content_request(message.lower())


def _looks_like_section_content_request(lowered_message: str) -> bool:
    content_intent_words = (
        "show",
        "show me",
        "give me",
        "paste",
        "print",
        "display",
        "what is in",
    )
    section_words = (
        "section",
        "block",
        "definition",
        "defined",
        "current",
        "existing",
        "here",
    )
    return any(word in lowered_message for word in content_intent_words) and any(
        word in lowered_message for word in section_words
    )
