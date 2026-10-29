"""Match config-relative includes using Klipper's non-recursive glob semantics."""

import fnmatch
import posixpath


def matches_include(path: str, source: str, pattern: str) -> bool:
    resolved = posixpath.normpath(posixpath.join(posixpath.dirname(source), pattern))
    parts, patterns = path.split("/"), resolved.split("/")
    return len(parts) == len(patterns) and all(
        fnmatch.fnmatchcase(part, match) and (not part.startswith(".") or match.startswith("."))
        for part, match in zip(parts, patterns)
    )
