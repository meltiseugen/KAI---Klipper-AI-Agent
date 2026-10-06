from __future__ import annotations

import re

from klipperai_agent.domain.evidence import ArtifactInput, ArtifactKind
from klipperai_agent.domain.messages import ChatHistoryMessage

_CONFIG_SECTION_PATTERN = re.compile(r"(?m)^\[[^\]\n]{1,160}\]\s*$")


_LOG_LINE_PATTERN = re.compile(
    r"(?m)^(?:"
    r"\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}"
    r"|[A-Z][a-z]{2}\s+\d+\s+\d{2}:\d{2}:\d{2}"
    r"|Start printer at "
    r"|Traceback \(most recent call last\):"
    r"|MCU .+"
    r"|!! .+"
    r")"
)


_MAX_HISTORY_CHARS_PER_MESSAGE = 1400


def _build_chat_artifacts(
    message: str,
    route: str,
    request_artifacts: list[ArtifactInput],
) -> list[ArtifactInput]:
    artifacts = list(request_artifacts)
    inline_artifact = _infer_inline_question_artifact(message, route)
    if inline_artifact is not None:
        artifacts.append(inline_artifact)
    return artifacts


def _format_conversation_context(history: list[ChatHistoryMessage], *, max_pairs: int) -> str:
    max_messages = max(0, max_pairs) * 2
    if max_messages <= 0:
        return ""

    lines: list[str] = []
    for item in history[-max_messages:]:
        text = item.text.strip()
        if not text:
            continue
        if len(text) > _MAX_HISTORY_CHARS_PER_MESSAGE:
            text = f"{text[:_MAX_HISTORY_CHARS_PER_MESSAGE]}\n...[truncated]..."
        role = "User" if item.role == "user" else "KlipperAI"
        lines.append(f"{role}: {text}")
    return "\n\n".join(lines)


def _build_contextual_classification_message(message: str, conversation_context: str) -> str:
    if not conversation_context:
        return message
    return (
        "Recent conversation:\n"
        f"{conversation_context}\n\n"
        "Current user message:\n"
        f"{message}\n\n"
        "Classify the current user message. Use the recent conversation only to resolve follow-ups like "
        "'do that', 'yes', 'show me that', or 'continue'."
    )


def _infer_inline_question_artifact(message: str, route: str) -> ArtifactInput | None:
    normalized = message.strip()
    if not normalized:
        return None

    line_count = normalized.count("\n") + 1
    looks_structured = bool(
        _CONFIG_SECTION_PATTERN.search(normalized) or _LOG_LINE_PATTERN.search(normalized)
    )
    if not looks_structured and line_count < 8:
        return None

    kind: ArtifactKind = "config_snippet" if _CONFIG_SECTION_PATTERN.search(normalized) else "notes"
    if route == "diagnostics" and _LOG_LINE_PATTERN.search(normalized):
        kind = "system_log"

    return ArtifactInput(
        kind=kind,
        label="question-context",
        content=normalized,
    )
