"""Line-oriented manual patches. Omitted options and unrelated sections are retained."""

from __future__ import annotations

import difflib
import hashlib
import posixpath
import re
from pathlib import PurePosixPath

from klipperai_agent.config.include_paths import matches_include
from klipperai_agent.config.models import ConfigDocument, ConfigSnapshot
from klipperai_agent.config.parser import ConfigParser
from klipperai_agent.config.review_parser import parse_review_config
from klipperai_agent.domain.proposals import ConfigFilePatch, ConfigProposal, ProposalReview
from klipperai_agent.domain.redaction import REDACTED
from klipperai_agent.knowledge.pins import config_gaps


def valid_target(path: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z0-9_./ -]+\.cfg", path)) and all(
        part not in {"", ".", ".."} for part in path.split("/")
    )


def _digest(document: ConfigDocument | None) -> str:
    if document is None:
        return "absent"
    return document.content_digest or hashlib.sha256(document.content.encode()).hexdigest()


def merge_options(content: str, snippet: str) -> str:
    """Merge provided options only; refuse ambiguous parsing and autosave collisions."""
    existing, errors = parse_review_config(content)
    proposed, problems = parse_review_config(snippet)
    if errors or problems or not proposed or ConfigParser.extract_include_patterns(snippet):
        raise ValueError(
            "A file patch requires unambiguous sections and options; include-only changes need manual review."
        )
    if REDACTED in content or REDACTED in snippet:
        raise ValueError("Redacted content cannot be used as a file patch baseline.")
    autosave = "\n".join(line[4:] for line in content.splitlines() if line.startswith("#*# "))
    saved_names = ConfigParser.extract_sections(autosave)
    if any(section.name in saved_names for section in proposed):
        raise ValueError(
            "A proposed section has SAVE_CONFIG values; reconcile those manually before drafting a patch."
        )
    lines = content.splitlines()
    current = {section.name: section for section in existing}
    changes: list[tuple[int, int, list[str]]] = []
    additions: list[str] = []
    for section in proposed:
        original = current.get(section.name)
        if original is None:
            additions.append(f"[{section.name}]")
            for option, value in section.values.items():
                additions.extend(_assignment(option, value))
            additions.append("")
            continue
        end = next(
            (
                i
                for i in range(original.line, len(lines))
                if re.match(r"\s*\[", lines[i]) or lines[i].startswith("#*#")
            ),
            len(lines),
        )
        new_options = []
        for option, value in section.values.items():
            if option not in original.values:
                new_options.extend(_assignment(option, value))
                continue
            if original.values[option] == value:
                continue
            start = original.lines[option] - 1
            stop = min([n - 1 for n in original.lines.values() if n - 1 > start] + [end])
            while stop > start + 1 and (
                not lines[stop - 1].strip() or lines[stop - 1].lstrip().startswith(("#", ";"))
            ):
                stop -= 1
            replacement = _assignment(option, value)
            # Retain comments, including inline comments on replaced assignments.
            for raw in lines[start:stop]:
                comment = re.search(r"#.*|(?<!\S);.*", raw)
                if comment:
                    replacement.append(comment[0])
            changes.append((start, stop, replacement))
        if new_options:
            changes.append((end, end, new_options))
    if additions:
        end = next((i for i, line in enumerate(lines) if line.startswith("#*#")), len(lines))
        changes.append((end, end, ["", *additions]))
    # At one insertion point, later sections must be inserted first so new options
    # remain in their original section, before the next header.
    ordered = sorted(enumerate(changes), key=lambda item: (item[1][0], item[0]), reverse=True)
    for _, (start, stop, replacement) in ordered:
        lines[start:stop] = replacement
    return "\n".join(lines).rstrip() + "\n"


def _assignment(option: str, value: str) -> list[str]:
    parts = value.split("\n")
    return [f"{option}: {parts[0]}".rstrip(), *(f"  {line}" for line in parts[1:])]


def file_patch(path: str, document: ConfigDocument | None, content: str) -> ConfigFilePatch:
    old = document.content.splitlines() if document else []
    diff = "\n".join(
        difflib.unified_diff(
            old,
            content.splitlines(),
            fromfile=f"a/{path}" if document else "/dev/null",
            tofile=f"b/{path}",
            lineterm="",
        )
    )
    return ConfigFilePatch(
        target_file=path,
        operation="update" if document else "create",
        baseline_digest=_digest(document),
        diff=diff + "\n" if diff else "",
    )


def attach_file_plan(
    proposal: ConfigProposal,
    snapshot: ConfigSnapshot,
    inventory: ConfigSnapshot,
    previous: ProposalReview | None,
) -> None:
    review = proposal.review
    assert review is not None
    path = proposal.target_file.replace("\\", "/")
    if not valid_target(path):
        review.errors.append(
            "File patches require a plain relative .cfg path without traversal or control characters."
        )
        review.status = "stale" if review.status == "stale" else "needs_information"
        return
    observed = {doc.path: doc for doc in inventory.documents}
    active = {doc.path: doc for doc in snapshot.documents}
    target = observed.get(path)
    managed = len(PurePosixPath(path).parts) == 2 and path.startswith("klipperai/")
    root = active.get(snapshot.root_file or "")
    baselines = {path: _digest(target)}
    if root:
        baselines[root.path] = _digest(root)
    review.file_baselines = (
        previous.file_baselines if previous and previous.file_baselines else baselines
    )
    if review.file_baselines != baselines:
        review.status = "stale"
        review.warnings.append(
            "A patch target or include baseline changed. Request a fresh proposal."
        )
    if review.status != "manual_review":
        return
    try:
        if path in active and _digest(active[path]) != _digest(target):
            raise ValueError(
                "The target changed during review. Refresh the proposal before editing."
            )
        if not target and not managed:
            raise ValueError(
                "New files must use klipperai/<feature>.cfg for a managed fragment plan."
            )
        if target and target.truncated:
            raise ValueError("The complete target file is required to generate a patch.")
        if target and path not in active and not managed:
            raise ValueError(
                "The target file is inactive; confirm its include relationship manually."
            )
        if not target or path not in active:
            gaps = [
                note
                for note in config_gaps(inventory)
                if not note.startswith(
                    (
                        "Auto-detected root config file:",
                        "Additional config file collected",
                        "Collected ",
                    )
                )
            ]
            # Empty wildcard includes are valid. A missing explicit include to this new
            # fragment is also resolved by this plan; all other collection gaps block it.
            gaps = [
                note
                for note in gaps
                if not (
                    note.startswith("Include pattern matched no files:")
                    and ("*" in note or "?" in note or f": {path} (" in note)
                )
            ]
            if gaps:
                raise ValueError(
                    "Incomplete file inventory; verify inactive files and include gaps before creating a fragment."
                )
        after = merge_options(target.content if target else "", proposal.config)
        patches = [file_patch(path, target, after)]
        if managed and path not in active:
            if root is None or root.truncated or REDACTED in root.content:
                raise ValueError(
                    "A complete unredacted root config is required for the managed include plan."
                )
            relative = posixpath.relpath(path, posixpath.dirname(root.path) or ".")
            directive = f"[include {relative}]"
            review.managed_include = f"Manually create or update {path} in the KlipperAI-owned klipperai directory. Load it from {root.path}; preserve all other files."
            included = any(
                matches_include(path, doc.path, pattern)
                for doc in snapshot.documents
                for pattern in ConfigParser.extract_include_patterns(doc.content)
            )
            if not included:
                lines = root.content.splitlines()
                index = next(
                    (i for i, line in enumerate(lines) if line.startswith("#*#")), len(lines)
                )
                lines[index:index] = ["", directive, ""]
                patches.append(file_patch(root.path, root, "\n".join(lines)))
            else:
                review.managed_include += " An existing include already covers this path."
        review.file_patches = [patch for patch in patches if patch.diff]
        review.warnings.append(
            "File patches merge supplied options and preserve omitted options. They are line-oriented drafts for manual editing, not file replacements or firmware validation."
        )
    except ValueError as exc:
        review.errors.append(str(exc))
        review.status = "needs_information"
