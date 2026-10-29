"""Public build identity supplied by the operator's code deployment tooling."""

import json
import re
from pathlib import Path

from klipperai_agent.domain.version import __version__


def release_info() -> dict[str, str]:
    path = Path(__file__).resolve().parents[1] / "build-info.json"
    try:
        with path.open(encoding="utf-8") as handle:
            data = json.loads(handle.read(4097))
        build = data.get("build", "") if isinstance(data, dict) else ""
        if not isinstance(build, str) or not re.fullmatch(r"[a-f0-9]{16}", build):
            build = "source"
    except (OSError, ValueError):
        build = "source"
    return {"version": __version__, "build": build}
