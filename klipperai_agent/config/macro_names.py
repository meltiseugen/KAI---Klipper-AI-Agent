from __future__ import annotations

import re

from klipperai_agent.config.vocabulary import (
    _DIRECT_SECTION_PATTERN,
    _MACRO_COMMAND_PATTERN,
    _MACRO_IDENTIFIER_PATTERN,
    _MACRO_NAME_BOUNDARY_WORDS,
    _MACRO_NAME_LEADING_WORDS,
    _MACRO_WORD_PATTERN,
)


def _extract_explicit_section_name(message: str) -> str | None:
    match = _DIRECT_SECTION_PATTERN.search(message)
    if not match:
        return None
    section = match.group(1).strip()
    return section or None


def _extract_macro_section_name(message: str) -> str | None:
    macro_word_match = _MACRO_WORD_PATTERN.search(message)
    if macro_word_match:
        before = message[: macro_word_match.start()]
        after = message[macro_word_match.end() :]
        near_macro = _last_macro_candidate(before) or _first_macro_candidate(after)
        if near_macro:
            return near_macro

    for match in _MACRO_IDENTIFIER_PATTERN.finditer(message):
        candidate = _normalize_macro_name_candidate(match.group(0), allow_plain=False)
        if candidate:
            return candidate

    for match in _MACRO_COMMAND_PATTERN.finditer(message):
        candidate = _normalize_macro_name_candidate(match.group(0), allow_plain=False)
        if candidate:
            return candidate

    return None


def _last_macro_candidate(text: str) -> str | None:
    identifier_matches = list(_MACRO_IDENTIFIER_PATTERN.finditer(text))
    for match in reversed(identifier_matches):
        candidate = _normalize_macro_name_candidate(match.group(0), allow_plain=True)
        if candidate:
            return candidate

    words = _macro_words(text)
    candidate_words: list[str] = []
    for word in reversed(words):
        if word.lower() in _MACRO_NAME_BOUNDARY_WORDS:
            break
        candidate_words.append(word)
        if len(candidate_words) == 4:
            break

    if not candidate_words:
        return None
    candidate_words.reverse()
    return _normalize_macro_name_candidate(" ".join(candidate_words), allow_plain=True)


def _first_macro_candidate(text: str) -> str | None:
    identifier_match = _MACRO_IDENTIFIER_PATTERN.search(text)
    if identifier_match:
        candidate = _normalize_macro_name_candidate(identifier_match.group(0), allow_plain=True)
        if candidate:
            return candidate

    words = _macro_words(text)
    while words and words[0].lower() in _MACRO_NAME_LEADING_WORDS:
        words.pop(0)

    candidate_words: list[str] = []
    for word in words:
        if word.lower() in _MACRO_NAME_BOUNDARY_WORDS:
            break
        candidate_words.append(word)
        if len(candidate_words) == 4:
            break

    if not candidate_words:
        return None
    return _normalize_macro_name_candidate(" ".join(candidate_words), allow_plain=True)


def _macro_words(text: str) -> list[str]:
    return re.findall(r"[A-Za-z][A-Za-z0-9_-]*", text)


def _normalize_macro_name_candidate(raw_name: str, *, allow_plain: bool) -> str | None:
    words = _macro_words(raw_name.replace("`", " "))
    while words and words[0].lower() in _MACRO_NAME_LEADING_WORDS:
        words.pop(0)
    while words and words[-1].lower() in _MACRO_NAME_BOUNDARY_WORDS:
        words.pop()

    if not words or len(words) > 4:
        return None

    if any(word.lower() in _MACRO_NAME_BOUNDARY_WORDS for word in words):
        return None

    if len(words) == 1 and not allow_plain and not _looks_like_macro_name_token(words[0]):
        return None

    macro_name = "_".join(word.replace("-", "_") for word in words).upper()
    if not re.fullmatch(r"[A-Z][A-Z0-9_]*", macro_name):
        return None
    return f"gcode_macro {macro_name}"


def _looks_like_macro_name_token(token: str) -> bool:
    return "_" in token or "-" in token or token.isupper()
