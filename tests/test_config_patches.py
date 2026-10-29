import hashlib

import pytest

from klipperai_agent.application.proposal_review import ProposalReviewService
from klipperai_agent.config.collector import ConfigCollector
from klipperai_agent.config.include_paths import matches_include
from klipperai_agent.config.models import ConfigDocument
from klipperai_agent.config.patches import file_patch, merge_options, valid_target
from klipperai_agent.config.review import ProposalReviewer
from klipperai_agent.domain.investigation import InvestigationResult
from klipperai_agent.domain.proposals import ConfigProposal
from tests.test_config_analysis import snapshot


def draft(path="printer.cfg", content="[fan]\nmax_power: 0.7"):
    return ConfigProposal(title="Draft", target_file=path, config=content, rationale="Manual edit")


def test_include_globs_stay_within_the_named_directory():
    assert matches_include("klipperai/new.cfg", "nested/printer.cfg", "../klipperai/*.cfg")
    assert not matches_include("klipperai/new.cfg", "printer.cfg", "*.cfg")
    assert not matches_include("klipperai/sub/new.cfg", "printer.cfg", "klipperai/*.cfg")
    assert not matches_include("klipperai/.hidden.cfg", "printer.cfg", "klipperai/*.cfg")
    assert matches_include("klipperai/.hidden.cfg", "printer.cfg", "klipperai/.*.cfg")
    tree = snapshot(("printer.cfg", "[printer]\nkinematics: cartesian\n[include *.cfg]"))
    result = reviewed(tree, draft("klipperai/test.cfg", "[gcode_macro TEST]\ngcode: M117 ok"))
    assert len(result.review.file_patches) == 2
    assert "+[include klipperai/test.cfg]" in result.review.file_patches[1].diff


def reviewed(tree, proposal=None, inventory=None, previous=None):
    return ProposalReviewer().review(
        proposal or draft(), tree, inventory=inventory or tree, previous=previous
    )


def test_merge_preserves_options_comments_macros_and_other_sections():
    old = """# header
[include unchanged.cfg]
[fan]
pin: PA1 # actual wiring
max_power: 0.8 ; power comment
# keep section comment
kick_start_time: 0.3

[gcode_macro TEST]
description: Keep me
gcode:
  G90
  # keep macro comment
  M117 Old

[printer]
kinematics: cartesian
"""
    new = merge_options(
        old,
        "[fan]\nmax_power: 0.7\nshutdown_speed: 0\n[gcode_macro TEST]\ngcode:\n  M117 New\n[respond]\n",
    )
    assert "pin: PA1 # actual wiring" in new
    assert "kick_start_time: 0.3" in new and "description: Keep me" in new
    assert "power comment" in new and "keep macro comment" in new
    assert "M117 New" in new and "M117 Old" not in new
    assert "[include unchanged.cfg]" in new and "[printer]\nkinematics: cartesian" in new
    assert "shutdown_speed: 0" in new and "[respond]" in new
    assert merge_options("[fan]\npin: PA1", "[fan]\npin: PA1") == "[fan]\npin: PA1\n"
    patch = file_patch("printer.cfg", ConfigDocument("printer.cfg", old, []), new)
    assert patch.baseline_digest == hashlib.sha256(old.encode()).hexdigest()
    assert "--- a/printer.cfg" in patch.diff and "+max_power: 0.7" in patch.diff
    assert "-pin: PA1" not in patch.diff and "-kinematics" not in patch.diff
    assert not file_patch("printer.cfg", ConfigDocument("printer.cfg", new, []), new).diff
    merged = merge_options("[fan]\npin: PA1", "[fan]\nmax_power: 0.5\n[respond]\n")
    assert merged.index("max_power") < merged.index("[respond]")


@pytest.mark.parametrize(
    "content,snippet,reason",
    [
        ("[fan]\npin: PA1\npin: PA2", "[fan]\npin: PA3", "unambiguous"),
        ("[fan]\npin: PA1", "[include x.cfg]", "unambiguous"),
        ("[fan]\npin: [REDACTED]", "[fan]\npin: PA1", "Redacted"),
        (
            "[input_shaper]\n#*# [input_shaper]\n#*# shaper_freq_x = 42",
            "[input_shaper]\nshaper_freq_x: 50",
            "SAVE_CONFIG",
        ),
    ],
)
def test_patch_refuses_ambiguous_redacted_and_saved_content(content, snippet, reason):
    with pytest.raises(ValueError, match=reason):
        merge_options(content, snippet)


def test_existing_patches_and_stale_baselines():
    tree = snapshot(("printer.cfg", "[fan]\npin: PA1\nmax_power: 0.8"))
    proposal = reviewed(tree)
    assert proposal.review.status == "manual_review" and proposal.review.file_patches
    assert proposal.review.file_baselines["printer.cfg"]
    invalid = reviewed(tree, draft("printer.cfg\nignored"))
    assert invalid.review.status == "needs_information" and not invalid.review.file_patches
    assert not valid_target("../printer.cfg") and not valid_target("/printer.cfg")
    changed = snapshot(("printer.cfg", "[fan]\npin: PA1\nmax_power: 0.9"))
    stale = reviewed(changed, previous=proposal.review)
    assert stale.review.status == "stale" and not stale.review.file_patches
    race = reviewed(tree, inventory=changed)
    assert any("changed during" in error for error in race.review.errors)
    blocked = reviewed(tree, draft(content="[fan]\nmax_power: 2"))
    assert not blocked.review.file_patches


def test_managed_fragment_creation_include_and_autosave_boundaries():
    tree = snapshot(
        (
            "nested/printer.cfg",
            "[printer]\nkinematics: cartesian\n#*# SAVE_CONFIG\n#*# [probe]\n#*# z_offset = 1",
        )
    )
    proposal = reviewed(
        tree, draft("klipperai/status.cfg", "[gcode_macro STATUS]\ngcode: M117 Ready")
    )
    review = proposal.review
    assert review.status == "manual_review" and len(review.file_patches) == 2
    fragment, include = review.file_patches
    assert fragment.operation == "create" and "--- /dev/null" in fragment.diff
    assert "+[include ../klipperai/status.cfg]" in include.diff
    assert include.diff.index("+[include") < include.diff.index(" #*# SAVE_CONFIG")
    assert review.managed_include and review.file_baselines["klipperai/status.cfg"] == "absent"
    added = snapshot(
        *[(doc.path, doc.content) for doc in tree.documents],
        ("klipperai/status.cfg", "[gcode_macro STATUS]\ngcode: M117 Existing"),
    )
    stale = reviewed(
        tree,
        draft("klipperai/status.cfg", "[gcode_macro STATUS]\ngcode: M117 Ready"),
        inventory=added,
        previous=review,
    )
    assert stale.review.status == "stale" and not stale.review.file_patches
    # Inactive files are merged, never silently overwritten or duplicated.
    existing = reviewed(
        tree,
        draft("klipperai/status.cfg", "[gcode_macro STATUS]\ngcode: M117 Ready"),
        inventory=added,
    )
    assert existing.review.file_patches[0].operation == "update"
    wildcard = snapshot(
        ("printer.cfg", "[printer]\nkinematics: cartesian\n[include klipperai/*.cfg]"),
        notes=["Include pattern matched no files: klipperai/*.cfg (from printer.cfg)"],
    )
    included = reviewed(
        wildcard, draft("klipperai/status.cfg", "[gcode_macro STATUS]\ngcode: M117 Ready")
    )
    assert (
        len(included.review.file_patches) == 1
        and "already covers" in included.review.managed_include
    )


@pytest.mark.parametrize(
    "case,reason",
    [
        ("unmanaged", "New files"),
        ("truncated", "complete target"),
        ("inactive", "inactive"),
        ("gaps", "Incomplete file inventory"),
        ("root", "root config"),
        ("redacted", "unredacted"),
    ],
)
def test_patch_plan_refuses_incomplete_evidence(case, reason):
    tree = snapshot(("printer.cfg", "[printer]\nkinematics: cartesian"))
    inventory = snapshot(("printer.cfg", tree.documents[0].content))
    proposal = draft("klipperai/test.cfg", "[gcode_macro TEST]\ngcode: M117 ok")
    if case == "unmanaged":
        proposal.target_file = "new.cfg"
    elif case == "truncated":
        inventory.documents.append(
            ConfigDocument("klipperai/test.cfg", "[gcode_macro TEST]", [], truncated=True)
        )
    elif case == "inactive":
        proposal.target_file = "old.cfg"
        inventory.documents.append(
            ConfigDocument("old.cfg", "[gcode_macro TEST]\ngcode: M117 old", [])
        )
    elif case == "gaps":
        inventory.notes.append("Could not read secret.cfg")
    elif case == "root":
        tree.root_file = "missing.cfg"
    else:
        tree.documents[0].content += "\n# [REDACTED]"
    result = reviewed(tree, proposal, inventory)
    assert result.review.status == "needs_information"
    assert reason in " ".join(result.review.errors)
    assert not result.review.file_patches


@pytest.mark.asyncio
async def test_service_patches_and_rechecks_do_not_write_printer_files(tmp_path):
    config = tmp_path / "config"
    config.mkdir()
    root = config / "printer.cfg"
    root.write_text("[printer]\nkinematics: cartesian\n[fan]\npin: PA1\nmax_power: 0.8")
    before = root.read_bytes()
    service = ProposalReviewService(ConfigCollector(tmp_path))
    result = InvestigationResult(config_proposals=[draft()])
    await service.review(result)
    assert result.config_proposals[0].review.file_patches
    await service.review(result, revalidate=True)
    assert result.config_proposals[0].review.status == "manual_review"
    assert root.read_bytes() == before
    assert sorted(path.name for path in config.iterdir()) == ["printer.cfg"]
    result = InvestigationResult(
        config_proposals=[
            draft(content="[fan]\nmax_power: 0.6"),
            draft(content="[fan]\nmax_power: 0.7"),
        ]
    )
    await service.review(result)
    assert all(
        p.review.status == "needs_information" and not p.review.file_patches
        for p in result.config_proposals
    )


@pytest.mark.asyncio
async def test_service_expands_only_patch_targets_and_blocks_filtered_absence(
    tmp_path, monkeypatch
):
    config = tmp_path / "config"
    config.mkdir()
    (config / "printer.cfg").write_text(
        "[fan]\npin: PA1\n" + "# retained comment\n" * 20 + "max_power: 0.8"
    )
    (config / "unrelated.cfg").write_text("[gcode_macro OLD]\ngcode: M117 Old\n" + "# long\n" * 20)
    reader = ConfigCollector(tmp_path, max_chars_per_document=25)
    result = InvestigationResult(config_proposals=[draft()])
    await ProposalReviewService(reader).review(result)
    assert result.config_proposals[0].review.file_patches
    assert "+max_power: 0.7" in result.config_proposals[0].review.file_patches[0].diff
    ignored = ConfigCollector(tmp_path, ignore_globs="klipperai/*")
    result = InvestigationResult(
        config_proposals=[draft("klipperai/status.cfg", "[gcode_macro STATUS]\ngcode: M117 ok")]
    )
    await ProposalReviewService(ignored).review(result)
    assert "Incomplete file inventory" in str(result.config_proposals[0].review.errors)
    # Redirected logical paths cannot establish that a fragment path is absent.
    original = reader._relative_path_string
    monkeypatch.setattr(
        reader,
        "_relative_path_string",
        lambda path: "redirected.cfg" if path.name == "unrelated.cfg" else original(path),
    )
    inventory = reader.collect_with_options(include_unincluded_configs=True)
    assert any("redirected" in note for note in inventory.notes)
