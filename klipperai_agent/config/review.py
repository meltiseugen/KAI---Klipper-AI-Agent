"""Conservative static review and section comparisons. This module never writes files."""

from __future__ import annotations

import difflib
import fnmatch
import re
from pathlib import PurePosixPath
from typing import Literal
from uuid import uuid4

from klipperai_agent.config.models import ConfigSnapshot
from klipperai_agent.config.parser import ConfigParser
from klipperai_agent.domain.investigation import utc_now
from klipperai_agent.domain.proposals import ConfigProposal, ProposalReview


class ProposalReviewer:
    def review(
        self,
        proposal: ConfigProposal,
        snapshot: ConfigSnapshot,
        *,
        previous: ProposalReview | None = None,
        expected_revision: str | None = None,
    ) -> ConfigProposal:
        errors: list[str] = []
        warnings = [
            "Manual editing only. KlipperAI has not changed any printer files.",
            "Static checks do not validate firmware option support, pin wiring, or physical safety.",
            "The comparison covers proposed sections only. Preserve all other content in the file.",
        ]
        path = proposal.target_file.replace("\\", "/")
        target = PurePosixPath(path)
        if (
            target.is_absolute()
            or ".." in target.parts
            or ":" in path
            or target.suffix.lower() != ".cfg"
        ):
            errors.append(
                "Choose a .cfg path relative to the printer config directory, without parent traversal."
            )
        sections = ConfigParser.extract_sections(proposal.config)
        normalized = [section.casefold() for section in sections]
        if not sections:
            errors.append("The proposal must contain at least one config section.")
        if len(normalized) != len(set(normalized)):
            errors.append("The proposal repeats a config section.")
        if re.search(r"\bYOUR_[A-Z0-9_]+\b|<[A-Z][A-Z0-9_]*>|\bTODO\b", proposal.config):
            errors.append("Resolve placeholder values before editing printer configuration.")
        if any(
            line.lstrip().startswith("[") and not re.match(r"^\s*\[[^\]\n]+\]\s*(?:[#;].*)?$", line)
            for line in proposal.config.splitlines()
        ):
            errors.append("A config section header is malformed.")
        if not snapshot.documents:
            errors.append(
                "Current configuration could not be inspected; conflicts cannot be checked."
            )
        if any(
            note for note in snapshot.notes if not note.startswith("Auto-detected root config:")
        ):
            warnings.append(
                "Configuration collection reported gaps or additional context; inspect its notes before editing."
            )
        for location in snapshot.section_locations:
            if location.section.casefold() in normalized and location.path != path:
                errors.append(
                    f"[{location.section}] already exists in {location.path}; edit that section instead of creating a duplicate."
                )
        document = next((item for item in snapshot.documents if item.path == path), None)
        if document is None:
            warnings.append(
                "The target is outside the observed active config tree. Verify whether it already exists and how it is included."
            )
        elif document.truncated:
            errors.append(
                "The target file excerpt is incomplete; a reliable section comparison is unavailable."
            )
        includes = ConfigParser.extract_include_patterns(proposal.config)
        for pattern in includes:
            include_path = (target.parent / pattern).as_posix()
            if not any(fnmatch.fnmatch(item.path, include_path) for item in snapshot.documents):
                warnings.append(
                    f"Include {pattern!r} could not be resolved from the observed config tree."
                )
        existing = "\n\n".join(
            snapshot.section_block(location) or ""
            for location in snapshot.section_locations
            if location.path == path and location.section.casefold() in normalized
        )
        if existing:
            warnings.append(
                "A proposed section may omit existing options or comments. Compare and merge it manually."
            )
        comparison = (
            "\n".join(
                difflib.unified_diff(
                    existing.splitlines(),
                    proposal.config.splitlines(),
                    fromfile=f"{path} (observed sections)",
                    tofile=f"{path} (proposed sections)",
                    lineterm="",
                )
            )
            if not (document and document.truncated)
            else ""
        )
        revision = snapshot.revision()
        baseline = previous.baseline_revision if previous else expected_revision or revision
        status: Literal["stale", "needs_information", "manual_review"] = (
            "stale" if baseline != revision else "needs_information" if errors else "manual_review"
        )
        if status == "stale":
            warnings.append(
                "Configuration changed since this proposal's evidence was collected. Request a refreshed proposal before editing."
            )
        review = ProposalReview(
            proposal_id=previous.proposal_id if previous else str(uuid4()),
            reviewed_at=utc_now(),
            status=status,
            baseline_revision=baseline,
            observed_revision=revision,
            errors=list(dict.fromkeys(errors)),
            warnings=warnings,
            comparison=comparison,
        )
        return proposal.copy(update={"review": review})
