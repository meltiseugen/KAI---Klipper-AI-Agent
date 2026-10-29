import hashlib
import json
from pathlib import Path

import pytest

from klipperai_agent.diagnostics.rules import RuleEngine
from klipperai_agent.domain.evidence import ArtifactInput

EXAMPLES = Path(__file__).resolve().parents[1] / "examples/failures"
CASES = json.loads((EXAMPLES / "cases.json").read_text())


@pytest.mark.parametrize("case", CASES, ids=[case["file"] for case in CASES])
def test_failure_example_findings_keep_original_evidence(case):
    path = EXAMPLES / case["file"]
    original = hashlib.sha256(path.read_bytes()).hexdigest()
    content = path.read_text()
    findings = RuleEngine().analyze(
        [ArtifactInput(kind="klippy_log", label=case["file"], content=content)]
    )
    assert sorted(finding.code for finding in findings) == sorted(case["expected"])
    for finding in findings:
        assert finding.citations and finding.citations[0].label == case["file"]
        assert finding.evidence.split(": ", 1)[1] in content
    assert hashlib.sha256(path.read_bytes()).hexdigest() == original
