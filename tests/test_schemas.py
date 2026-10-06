from klipperai_agent.contracts.api import ArtifactInput, ConfigProposal, _stringify_dict


def test_artifact_prompt_excerpt_full_and_truncated() -> None:
    artifact = ArtifactInput(content="abcdef")
    assert artifact.prompt_excerpt(10) == "abcdef"
    assert artifact.prompt_excerpt(3) == "abc\n...[truncated]..."


def test_config_proposal_normalizes_provider_shapes() -> None:
    base = {
        "title": "Fan",
        "target_file": "fan.cfg",
        "config": "[fan]",
        "rationale": "test",
    }
    assert ConfigProposal(**base, assumptions=None).assumptions == []
    assert ConfigProposal(**base, assumptions=" pin ").assumptions == ["pin"]
    assert ConfigProposal(**base, assumptions=" ").assumptions == []
    proposal = ConfigProposal(
        **base,
        assumptions=[None, {"summary": "from dict"}, 3],
        warnings={"message": "warning"},
    )
    assert proposal.assumptions == ["from dict", "3"]
    assert proposal.warnings == ["warning"]
    assert _stringify_dict({"count": 2}) == '{"count": 2}'
    assert _stringify_dict({"bad": object()}).startswith("{'bad':")
