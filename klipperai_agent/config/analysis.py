"""Static checks of the active on-disk tree; never a firmware validation result."""

from __future__ import annotations

import glob
import re

from klipperai_agent.config.include_paths import matches_include
from klipperai_agent.config.models import ConfigSnapshot
from klipperai_agent.config.review_parser import parse_review_config
from klipperai_agent.domain.config_analysis import ConfigAnalysis
from klipperai_agent.domain.evidence import IssueFinding, SourceCitation
from klipperai_agent.knowledge.pins import config_gaps, pin_ownership


def analyze_config(snapshot: ConfigSnapshot) -> ConfigAnalysis:
    findings: list[IssueFinding] = []
    citations: list[SourceCitation] = []
    notes = config_gaps(snapshot)
    complete = (
        bool(snapshot.documents)
        and not notes
        and not any(doc.truncated for doc in snapshot.documents)
    )

    def add(
        code: str, message: str, path: str, line: int, evidence: str, *, blocking: bool = False
    ) -> None:
        findings.append(
            IssueFinding(
                code=code,
                severity="high" if blocking else "medium",
                source=f"{path}:{line}",
                summary=message,
                evidence=evidence[:1200],
                proposed_fix="Inspect the cited configuration and correct it manually; re-run analysis after editing.",
                confidence="medium",
                confidence_scope="observation",
                confidence_reason="Static analysis of the collected on-disk tree supports this check. Includes may be incomplete; firmware compatibility and physical wiring are not verified.",
            )
        )
        citations.append(
            SourceCitation(
                label=f"{path}:{line}", path=path, line_number=line, excerpt=evidence[:1200]
            )
        )

    edges: dict[str, list[str]] = {}
    sections: dict[str, list[tuple[str, int]]] = {}
    for doc in snapshot.documents:
        if doc.truncated:
            notes.append(f"Incomplete file: {doc.path}; checks cover only its opening excerpt.")
        _, syntax = parse_review_config(doc.content)
        for check in syntax:
            add(
                "config_syntax",
                "Ambiguous configuration syntax (including possible overrides).",
                doc.path,
                check.line or 1,
                check.message,
            )
        for line_number, raw in enumerate(doc.content.splitlines(), 1):
            header = re.match(r"^\s*\[([^]]+)\]\s*$", raw.split("#", 1)[0].split(";", 1)[0])
            if not header:
                continue
            section = header[1].strip()
            if section.startswith("include "):
                pattern = section[8:].strip()
                matches = [
                    item.path
                    for item in snapshot.documents
                    if matches_include(item.path, doc.path, pattern)
                ]
                edges.setdefault(doc.path, []).extend(matches)
                if not matches:
                    wildcard = glob.has_magic(pattern)
                    add(
                        "empty_include_glob" if wildcard else "missing_include",
                        "Include wildcard has no observed matches (allowed by Klipper)."
                        if wildcard
                        else "Included file is missing or was not collected.",
                        doc.path,
                        line_number,
                        f"[{section}]",
                        blocking=not wildcard,
                    )
            else:
                sections.setdefault(section, []).append((doc.path, line_number))
    for name, locations in sections.items():
        if len(locations) > 1:
            path, line = locations[-1]
            add(
                "section_override",
                f"[{name}] has multiple definitions; inspect include order and conflicting options.",
                path,
                line,
                "; ".join(f"{p}:{n}" for p, n in locations),
            )
    if "safe_z_home" in sections and "homing_override" in sections:
        path, line = sections["homing_override"][0]
        add(
            "conflicting_homing",
            "safe_z_home and homing_override cannot be used together.",
            path,
            line,
            "[safe_z_home] and [homing_override]",
            blocking=True,
        )

    # Iterative traversal avoids Python recursion limits on large include trees.
    pending: list[tuple[str, tuple[str, ...]]] = [(snapshot.root_file or "", ())]
    visited: set[str] = set()
    while pending:
        path, ancestors = pending.pop()
        if path in ancestors:
            add(
                "include_cycle",
                "Recursive include chain.",
                str(path),
                1,
                " -> ".join((*ancestors, str(path))),
                blocking=True,
            )
        elif path and path not in visited:
            visited.add(path)
            pending.extend((child, (*ancestors, path)) for child in edges.get(path, []))

    pins = pin_ownership(snapshot)
    for row in pins["rows"]:
        option, section, value = row["option"], row["section"], row["value"]
        if (
            section.startswith(("gcode_macro ", "board_pins", "multi_pin "))
            or section == "duplicate_pin_override"
        ):
            continue
        if option != "pin" and not option.endswith("_pin"):
            continue
        # Pin names depend on firmware; check description grammar, not a board whitelist.
        stripped = re.sub(r"^[\^~]?\s*!?\s*", "", value).strip()
        if stripped == "probe:z_virtual_endstop" and not any(
            name in {"probe", "bltouch", "smart_effector"} or name.startswith("probe_eddy_current ")
            for name in sections
        ):
            add(
                "missing_virtual_probe",
                "Virtual probe endstop has no observed probe section.",
                row["path"],
                row["line"],
                f"[{section}] {option}: {value}",
            )
        if not stripped or re.search(r"[\s!^~<>]", stripped) or stripped.count(":") > 1:
            add(
                "invalid_pin",
                "Malformed or unresolved pin description.",
                row["path"],
                row["line"],
                f"[{section}] {option}: {value}",
                blocking=True,
            )
        elif ":" in stripped and stripped.split(":", 1)[0] not in pins["mcus"]:
            chip = stripped.split(":", 1)[0]
            if chip not in {"probe", "multi_pin"} and not chip.startswith("tmc"):
                add(
                    "unknown_pin_chip",
                    "Pin references an unobserved MCU or extension chip.",
                    row["path"],
                    row["line"],
                    f"[{section}] {option}: {value}",
                )
    for pin, owners in pins["owners"].items():
        owners = [row for row in owners if row["section"] != "duplicate_pin_override"]
        if len(owners) > 1:
            row = owners[0]
            add(
                "shared_pin",
                f"{pin} has multiple uses; confirm whether sharing is supported.",
                row["path"],
                row["line"],
                "; ".join(
                    f"{item['path']}:{item['line']} [{item['section']}] {item['option']}"
                    for item in owners
                ),
            )
    for gap in pins["gaps"]:
        if gap not in notes:
            notes.append(gap)
    notes.append(
        "Static analysis of active files on disk, not Klipper's loaded state. Physical pins, firmware extensions, shared buses and SAVE_CONFIG values require manual verification."
    )
    if len(findings) > 80:
        complete = False
        notes.append("Findings limited to 80; resolve these and analyze again.")
    return ConfigAnalysis(
        revision=snapshot.revision(),
        root_file=snapshot.root_file,
        complete=complete,
        files_checked=len(snapshot.documents),
        findings=findings[:80],
        citations=citations[:80],
        notes=notes,
    )
