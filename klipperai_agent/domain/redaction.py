"""Best-effort credential removal at public evidence boundaries; preserves lines."""

from __future__ import annotations

import re
from typing import Any

REDACTED = "[REDACTED]"
_KEY = r"(?:[a-z0-9]+[_-])*(?:api[_-]?key|access[_-]?token|refresh[_-]?token|token|secret|password|passwd|passphrase|authorization|cookie|session[_-]?id|session|wifi[_-]?psk|psk)"
_ASSIGNMENT = re.compile(
    rf"(?i)(?<![\w-])([\"']?{_KEY}[\"']?[ \t]*[:=][ \t]*)(\"[^\"\r\n]*\"|'[^'\r\n]*'|[^\r\n,;&}}]+)"
)
_PRIVATE_KEY = re.compile(
    r"-----BEGIN (?:[A-Z0-9 ]+ )?PRIVATE KEY-----.*?(?:-----END (?:[A-Z0-9 ]+ )?PRIVATE KEY-----|\Z)",
    re.S,
)
_MULTILINE = re.compile(
    rf"(?im)^(?P<indent>[ \t]*)(?P<key>{_KEY}[ \t]*[:=][ \t]*)(?:[|>][+-]?)?[ \t]*\r?\n"
    r"(?P<body>(?:(?P=indent)[ \t]+[^\r\n]+(?:\r?\n|\Z))+)"
)


def _mask(value: str) -> str:
    # Never expand a short value beyond existing evidence/schema limits.
    width = len(value) - value.count("\n") - value.count("\r")
    return (REDACTED if width >= len(REDACTED) else "*" * width) + "\n" * value.count("\n")


def redact_text(text: str, secrets: tuple[str, ...] = ()) -> str:
    for secret in secrets:
        if secret:
            text = text.replace(secret, _mask(secret))
    text = _PRIVATE_KEY.sub(lambda match: _mask(match[0]), text)
    text = _MULTILINE.sub(
        lambda match: match["indent"] + match["key"] + _mask(match["body"]) + "\n",
        text,
    )
    text = re.sub(
        r"(?im)\b(authorization|proxy-authorization|cookie|set-cookie)([ \t]*:[ \t]*)([^\r\n]+)",
        lambda match: match[1] + match[2] + _mask(match[3]),
        text,
    )
    text = re.sub(
        r"(?i)([a-z][a-z0-9+.-]*://)([^\s/@]+:[^\s/@]+)@",
        lambda match: match[1] + _mask(match[2]) + "@",
        text,
    )
    text = re.sub(r"\bsk-(?:proj-|svcacct-)?[A-Za-z0-9_-]{12,}\b", REDACTED, text)
    text = re.sub(
        r"(?i)\b((?:Bearer|Basic)[ \t]+)([A-Za-z0-9_+/=.-]+)",
        lambda match: match[1] + _mask(match[2]),
        text,
    )
    return _ASSIGNMENT.sub(
        lambda match: (
            match[1]
            + (
                match[2][0] + _mask(match[2][1:-1]) + match[2][0]
                if match[2].startswith(('"', "'"))
                else _mask(match[2])
            )
        ),
        text,
    )


def redact_data(value: Any, secrets: tuple[str, ...] = ()) -> Any:
    if isinstance(value, str):
        return redact_text(value, secrets)
    if isinstance(value, dict):
        return {
            key: REDACTED if re.fullmatch(_KEY, str(key), re.I) else redact_data(item, secrets)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [redact_data(item, secrets) for item in value]
    return value
