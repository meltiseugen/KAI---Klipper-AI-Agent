"""Conservative static review and section comparisons. This module never writes files."""

from __future__ import annotations

import difflib
import fnmatch
import re
from pathlib import PurePosixPath
from typing import Literal
from uuid import uuid4

from klipperai_agent.config.models import ConfigSnapshot
from klipperai_agent.config.option_review import review_options
from klipperai_agent.config.parser import ConfigParser
from klipperai_agent.config.patches import attach_file_plan
from klipperai_agent.config.review_guidance import manual_verification
from klipperai_agent.config.review_parser import parse_review_config
from klipperai_agent.config.review_versions import exact_klipper_release
from klipperai_agent.domain.investigation import utc_now
from klipperai_agent.domain.proposals import ConfigProposal, ProposalReview, ReviewFirmware


class ProposalReviewer:
    def review(
        self,
        proposal: ConfigProposal,
        snapshot: ConfigSnapshot,
        *,
        previous: ProposalReview | None = None,
        expected_revision: str | None = None,
        firmware: ReviewFirmware | None = None,
        inventory: ConfigSnapshot | None = None,
    ) -> ConfigProposal:
        errors: list[str] = []
        warnings = [
            "Manual editing only. KlipperAI has not changed any printer files.",
            "Bundled option checks are partial. They do not certify the installed firmware, pin wiring, macro execution or physical safety.",
            "The comparison covers proposed sections only. Preserve all other content in the file.",
        ]
        firmware = firmware or ReviewFirmware()
        parsed, checks = parse_review_config(proposal.config)
        checks.extend(
            review_options(parsed, snapshot, proposal.target_file.replace("\\", "/"), firmware)
        )
        for check in checks:
            check_location = (
                f"[{check.section}] {check.option} (line {check.line}): " if check.section else ""
            )
            if check.severity == "error":
                errors.append(check_location + check.message)
            elif check.severity == "warning":
                warnings.append(check_location + check.message)
        if not exact_klipper_release(firmware):
            warnings.append(
                "No exact bundled Klipper release match. Git builds, dirty trees, unknown versions and forks require commit-specific option verification."
            )
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
        sections = [section.name for section in parsed] or ConfigParser.extract_sections(
            proposal.config
        )
        normalized = [section.casefold() for section in sections]
        if not sections:
            errors.append("The proposal must contain at least one config section.")
        if len(normalized) != len(set(normalized)):
            errors.append("The proposal repeats a config section.")
        if re.search(r"\bYOUR_[A-Z0-9_]+\b|<[A-Z][A-Z0-9_]*>|\bTODO\b", proposal.config):
            errors.append("Resolve placeholder values before editing printer configuration.")
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
        baseline_firmware = previous.baseline_firmware if previous else firmware
        firmware_observed = not (
            baseline_firmware
            and baseline_firmware.source == "live_version_saved_flavor"
            and firmware.source != "live_version_saved_flavor"
        )
        if not firmware_observed:
            warnings.append(
                "The previous live firmware version could not be rechecked. Saved profile values do not establish a firmware change; verify the running version before editing."
            )
        firmware_changed = bool(
            firmware_observed
            and baseline_firmware
            and baseline_firmware.version
            and firmware.version
            and (baseline_firmware.version, baseline_firmware.flavor.casefold())
            != (firmware.version, firmware.flavor.casefold())
        )
        status: Literal["stale", "needs_information", "manual_review"] = (
            "stale"
            if baseline != revision or firmware_changed or (previous and previous.status == "stale")
            else "needs_information"
            if errors
            else "manual_review"
        )
        if status == "stale":
            warnings.append(
                "Configuration or firmware changed since this proposal's evidence was collected, or this proposal was already stale. Request a refreshed proposal before editing."
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
            checks=checks,
            manual_steps=manual_verification(parsed),
            firmware=firmware,
            baseline_firmware=baseline_firmware,
        )
        result = proposal.copy(update={"review": review})
        if inventory is not None:
            attach_file_plan(result, snapshot, inventory, previous)
        return result
