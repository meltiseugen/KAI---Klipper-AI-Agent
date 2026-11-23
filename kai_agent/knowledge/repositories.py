"""Select readable hardware references from public repository metadata, not HTML."""

from __future__ import annotations

import re
from pathlib import PurePosixPath
from urllib.parse import unquote, urlsplit


def repository_location(url: str) -> tuple[str, str, str] | None:
    """Return GitHub repository, ref and optional subtree for repository indexes."""
    parsed = urlsplit(url)
    if parsed.hostname != "github.com":
        return None
    parts = [unquote(part) for part in parsed.path.strip("/").split("/")]
    if len(parts) < 2 or not all(re.fullmatch(r"[\w.-]+", p) for p in parts[:2]):
        return None
    repository = "/".join(parts[:2]).removesuffix(".git")
    if len(parts) == 2:
        return repository, "HEAD", ""
    if len(parts) >= 4 and parts[2] == "tree" and all(parts[3:]):
        return repository, parts[3], "/".join(parts[4:])
    return None


def reference_paths(tree: dict, prefix: str = "") -> list[str]:
    """Prefer nested manuals/configs; exclude binaries, 3D assets and oversized files."""
    if tree.get("truncated") or not isinstance(tree.get("tree"), list):
        raise ValueError("Repository file listing is incomplete; no homepage was cached.")
    candidates: list[tuple[int, str]] = []
    for entry in tree["tree"]:
        if not isinstance(entry, dict) or entry.get("type") != "blob":
            continue
        path, size = entry.get("path"), entry.get("size")
        if not isinstance(path, str) or not isinstance(size, int) or not 0 < size <= 8 * 1024**2:
            continue
        parts = path.split("/")
        if any(part in {"", ".", ".."} for part in parts):
            continue
        if prefix and not path.startswith(prefix.rstrip("/") + "/"):
            continue
        lowered = path.casefold()
        if any(part.casefold() in {"3d", "cad", "models", ".github"} for part in parts[:-1]):
            continue
        suffix = PurePosixPath(path).suffix.casefold()
        if suffix == ".cfg":
            rank = 0
        elif suffix in {".md", ".rst", ".txt"}:
            rank = 2
        elif suffix in {".pdf", ".png", ".jpg", ".jpeg"} and any(
            token in lowered
            for token in (
                "manual",
                "guide",
                "schematic",
                "-sch",
                "pin",
                "interface",
                "wiring",
                "datasheet",
            )
        ):
            rank = 1 if suffix == ".pdf" else 3
        else:
            continue
        candidates.append((rank, path))
    # Hardware/ often contains a newer copy of the manual also present at the root.
    selected: dict[str, tuple[int, str]] = {}
    for rank, path in sorted(candidates, key=lambda item: (-item[1].count("/"), item[1])):
        key = PurePosixPath(path).name.casefold() if rank in {1, 3} else path
        selected.setdefault(key, (rank, path))
    paths = [path for _, path in sorted(selected.values())]
    if not paths or len(paths) > 64:
        raise ValueError(
            "No bounded set of repository references found; use a specific documentation folder."
        )
    return paths
