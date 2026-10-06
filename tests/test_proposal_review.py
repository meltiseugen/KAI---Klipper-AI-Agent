from __future__ import annotations

import pytest

from klipperai_agent.application.proposal_review import ProposalReviewService
from klipperai_agent.config.collector import ConfigCollector
from klipperai_agent.config.models import ConfigDocument, ConfigSnapshot
from klipperai_agent.config.review import ProposalReviewer
from klipperai_agent.domain.investigation import InvestigationResult
from klipperai_agent.domain.proposals import ConfigProposal


def proposal(**kwargs):
    return ConfigProposal(
        **{
            "title": "Draft",
            "target_file": "extra.cfg",
            "config": "[fan]\npin: PA1",
            "rationale": "Manual draft",
            **kwargs,
        }
    )


def test_proposal_review_marks_uncertainty_and_conflicts(tmp_path):
    config = tmp_path / "config"
    config.mkdir()
    (config / "printer.cfg").write_text(
        "[printer]\nkinematics: cartesian\n[fan]\npin: PA1\n", encoding="utf-8"
    )
    snapshot = ConfigCollector(tmp_path).collect()
    reviewer = ProposalReviewer()
    valid = reviewer.review(proposal(target_file="printer.cfg", config="[fan]\npin: PA2"), snapshot)
    assert valid.review.status == "manual_review"
    assert "observed sections" in valid.review.comparison
    assert "preserve" in " ".join(valid.review.warnings).lower()
    duplicate = reviewer.review(proposal(), snapshot)
    assert duplicate.review.status == "needs_information"
    assert "already exists" in duplicate.review.errors[0]
    repeated = reviewer.review(proposal(config="[fan]\npin: PA1\n[fan]\npin: PA2"), snapshot)
    assert any("repeats" in error for error in repeated.review.errors)
    risky = reviewer.review(
        proposal(
            target_file="../printer.cfg",
            config="[broken\n[fan]\npin: YOUR_PIN\n[fan]\n[include missing.cfg]",
        ),
        snapshot,
    )
    assert len(risky.review.errors) >= 4
    assert any("Include" in warning for warning in risky.review.warnings)
    empty = reviewer.review(
        proposal(config="pin: PA1"),
        ConfigSnapshot(root_file=None, documents=[], notes=["Missing root"]),
    )
    assert len(empty.review.errors) == 2
    assert any("gaps" in warning for warning in empty.review.warnings)
    clipped = ConfigCollector(tmp_path, max_chars_per_document=20).collect()
    incomplete = reviewer.review(proposal(target_file="printer.cfg"), clipped)
    assert not incomplete.review.comparison
    assert any("incomplete" in error for error in incomplete.review.errors)
    assert reviewer.review(proposal(), snapshot, expected_revision="old").review.status == "stale"


def test_revision_includes_content_beyond_excerpt(tmp_path):
    config = tmp_path / "config"
    config.mkdir()
    path = config / "printer.cfg"
    path.write_text("[printer]\n" + "# long comment\n" * 20 + "# old", encoding="utf-8")
    collector = ConfigCollector(tmp_path, max_chars_per_document=40)
    old = collector.collect()
    path.write_text(path.read_text(encoding="utf-8").replace("# old", "# new"), encoding="utf-8")
    new = collector.collect()
    assert new.documents[0].content == old.documents[0].content
    assert new.revision() != old.revision()
    assert ConfigSnapshot.from_state(new.to_state()).revision() == new.revision()
    unversioned = ConfigSnapshot(
        root_file="printer.cfg", documents=[ConfigDocument("printer.cfg", "[printer]", ["printer"])]
    )
    assert unversioned.revision()


@pytest.mark.asyncio
async def test_review_service_has_no_work_without_proposals(tmp_path):
    await ProposalReviewService(ConfigCollector(tmp_path)).review(InvestigationResult())
