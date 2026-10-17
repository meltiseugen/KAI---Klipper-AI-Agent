"""Render a reversible local OE patch without modifying the checkout itself.

PatchFiles owns backups and deployment. This pure text engine validates both
outputs before either target file can be changed.
"""

from __future__ import annotations

import json
import re
from pathlib import Path


class RoutePatch:
    def __init__(self, prefix: str = "/klipperai", port: str = "8811", target: str = "_blank"):
        if not re.fullmatch(r"/[A-Za-z0-9_-]+(?:/[A-Za-z0-9_-]+)*", prefix):
            raise ValueError(
                "Prefix must contain non-empty path segments (letters, numbers, _ or -)"
            )
        if not port.isascii() or not port.isdigit() or not 1 <= int(port) <= 65535:
            raise ValueError("Port must be between 1 and 65535")
        if target not in ("_blank", "_self"):
            raise ValueError("Navigation target must be _blank or _self")
        self.prefix = prefix
        self.port = str(int(port))
        self.target = target
        self.templates = Path(__file__).parent

    @staticmethod
    def remove_block(text: str, start: str, end: str, blank: bool = False) -> str:
        starts, ends = text.count(start), text.count(end)
        if starts != ends or starts > 1:
            raise ValueError(f"Incomplete or duplicate patch markers: {start}")
        suffix = r"\n(?:\n)?" if blank else r"(?:\n|$)"
        pattern = re.compile(
            r"^[ \t]*" + re.escape(start) + r"[^\n]*\n.*?"
            r"^[ \t]*" + re.escape(end) + r"[^\n]*" + suffix,
            re.MULTILINE | re.DOTALL,
        )
        result, count = pattern.subn("", text)
        if count != starts:
            raise ValueError(f"Unrecognized patch block: {start}")
        return result

    def remove(self, router: str, ui: str) -> tuple[str, str]:
        for brand in ("KlipperAI", "KlippyAI"):
            for part in ("init", "helper", "map"):
                marker = f"# {brand} local route patch {part}"
                router = self.remove_block(
                    router, marker + " start", marker + " end", part != "map"
                )
            marker = f"// {brand} local route patch"
            ui = self.remove_block(ui, marker + " start", marker + " end")
        compile(router, "moonrakerapirouter.py", "exec")
        return router, ui

    @staticmethod
    def insert(text: str, anchor: str, block: str) -> str:
        if text.count(anchor) != 1:
            raise ValueError(
                f"Expected exactly one upstream anchor: {anchor!r}; checkout unchanged"
            )
        return text.replace(anchor, block + anchor, 1)

    def apply(self, router: str, ui: str) -> tuple[str, str]:
        router, ui = self.remove(router, ui)
        blocks = (self.templates / "router.template").read_text(encoding="utf-8")
        blocks = blocks.replace("@@klipperai_prefix@@", self.prefix).replace(
            "@@klipperai_port@@", self.port
        )
        init, helper, mapping = blocks.split("\n@@BLOCK@@\n")
        # Insert mapping first; the helper also contains relativeUrlLower.
        router = self.insert(
            router, "            relativeUrlLower = relativeUrl.lower()\n", mapping
        )
        router = self.insert(router, "    # !! Interface Function !!", helper)
        router = self.insert(
            router,
            '        self.Logger.info("MoonrakerApiRouter using bound to moonraker at "+self.MoonrakerHostAndPortStr)\n',
            init,
        )
        navigation = (self.templates / "navigation.js").read_text(encoding="utf-8")
        navigation = navigation.replace("@@PREFIX@@", json.dumps(self.prefix + "/"))
        navigation = navigation.replace("@@TARGET@@", json.dumps(self.target))
        ui = self.insert(ui, "    oe_detect_oe_loaded_index_and_inject_helpers();\n", navigation)
        compile(router, "moonrakerapirouter.py", "exec")
        return router, ui
