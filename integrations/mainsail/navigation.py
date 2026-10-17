"""Pure transforms for Mainsail's supported .theme/navi.json sidebar entries."""

from __future__ import annotations

import json
from dataclasses import dataclass
from urllib.parse import urlsplit


@dataclass(frozen=True)
class NavigationEntry:
    title: str = "KlipperAI"
    href: str = "/klipperai/"
    target: str = "_blank"
    position: int = 85
    icon: str = ""

    def __post_init__(self):
        url = urlsplit(self.href)
        if (
            not self.title.strip()
            or not self.href
            or any(ord(c) < 32 for c in self.title + self.href + self.icon)
            or "\\" in self.href
            or not (
                (self.href.startswith("/") and not self.href.startswith("//"))
                or (url.scheme in ("https", "http") and url.netloc)
            )
        ):
            raise ValueError("Use a non-empty title and a local path or HTTP(S) navigation URL")
        if self.target not in ("_self", "_blank"):
            raise ValueError("Navigation target must be _self or _blank")
        if type(self.position) is not int or self.position < 0:
            raise ValueError("Navigation position must be a non-negative integer")

    def payload(self) -> dict:
        value = dict(title=self.title, href=self.href, target=self.target, position=self.position)
        if self.icon:
            value["icon"] = self.icon
        return value


def update_navigation(original: bytes | None, entry: NavigationEntry, remove: bool = False):
    items = json.loads(original.decode("utf-8-sig")) if original is not None else []
    if not isinstance(items, list):
        raise ValueError("Existing navi.json must contain a JSON array")
    # Retain the original helper's title/href identity, including duplicate cleanup.
    matches = [
        i
        for i, item in enumerate(items)
        if isinstance(item, dict)
        and (item.get("title") == entry.title or item.get("href") == entry.href)
    ]
    if (remove and not matches) or (
        not remove and len(matches) == 1 and items[matches[0]] == entry.payload()
    ):
        return original
    result = [item for i, item in enumerate(items) if i not in matches]
    if not remove:
        # Mainsail sorts by position. Preserve other entries and their file order.
        result.insert(matches[0] if matches else len(result), entry.payload())
    return (json.dumps(result, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
