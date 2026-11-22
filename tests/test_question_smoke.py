"""Offline checks for the live harness; these never contact a printer or provider."""

import io
import json
from unittest.mock import Mock

import pytest

from tools.question_smoke import CASES, evaluate
from tools.smoke_questions import KAIClient, run_cases


def complete():
    return {
        "response": "The saved profile reports Kalico; the board model is unknown.",
        "agent_status": "completed",
        "model_usage": {"status": "completed", "requests_completed": 2},
        "answer_claims": [{"claim": "Saved firmware", "citations": [{"evidence_id": "saved"}]}],
        "moonraker_reachable": True,
    }


def test_smoke_rejects_the_reported_step_limit_even_with_http_success():
    result = complete()
    result.update(agent_status="limited", response="The investigation reached its step limit.")
    assert evaluate(CASES[0], result) == ["agent did not complete", "no usable final answer"]


def test_smoke_requires_grounding_live_usage_and_correct_connection_state():
    assert evaluate(CASES[0], complete()) == []
    result = complete()
    result.update(
        answer_claims=[], model_usage={}, moonraker_reachable=False, config_proposals=[{}]
    )
    assert evaluate(CASES[2], result) == [
        "no completed live model request",
        "printer-specific answer lacks grounded claims",
        "current printer reachability was not established",
        "unexpected configuration draft for a non-editing question",
    ]


def test_client_reads_heartbeat_action_and_multiline_final_sse_without_credentials(monkeypatch):
    client = KAIClient("http://localhost:8080/kai/")
    assert client.origin == "http://localhost:8080"
    assert client.base == "http://localhost:8080/kai/api/"
    stream = (
        ': keep-alive\n\nevent: agent\ndata: {"message":"Read configuration"}\n\n'
        'event: result\ndata: {"response":\ndata: "Eddy is configured."}\n\n'
    )
    request = Mock(return_value=io.BytesIO(stream.encode()))
    monkeypatch.setattr(client, "request", request)
    result, events = client.ask("ephemeral-session", CASES[0])
    assert result["response"] == "Eddy is configured."
    assert events[0]["data"]["message"] == "Read configuration"
    assert request.call_args.args[0] == "chat/stream"
    assert request.call_args.args[1]["message"] == "what components do i have installed?"


@pytest.mark.parametrize("base", ["file:///etc/passwd", "http://user:secret@localhost/kai"])
def test_client_rejects_non_http_targets_and_embedded_secrets(base):
    with pytest.raises(ValueError):
        KAIClient(base)


@pytest.mark.parametrize(
    "stream,match",
    [
        ('event: error\ndata: {"message":"busy"}\n\n', "busy"),
        (": heartbeat\n\n", "without a final result"),
    ],
)
def test_client_does_not_accept_error_or_incomplete_stream(monkeypatch, stream, match):
    client = KAIClient("http://localhost/kai")
    monkeypatch.setattr(client, "request", lambda *args: io.BytesIO(stream.encode()))
    with pytest.raises(RuntimeError, match=match):
        client.ask("session", CASES[0])


def test_runner_stops_at_case_boundary_for_budget_and_leaves_review_explicit(tmp_path):
    client = Mock(base="http://localhost/kai/api/")
    client.ask.return_value = (complete(), [])
    output = tmp_path / "report.json"
    report = run_cases(client, CASES[:2], output, request_budget=2)
    assert len(report["cases"]) == 1 and report["unrun"] == ["firmware"]
    assert report["cases"][0]["human_review"] == "required"
    assert report["requests_completed"] == 2
    assert json.loads(output.read_text())["completed_at"]


def test_runner_preserves_failure_report_and_never_retries_ambiguous_requests(tmp_path):
    client = Mock(base="http://localhost/kai/api/")
    client.ask.side_effect = OSError("connection lost")
    report = run_cases(client, CASES[:2], tmp_path / "report.json", request_budget=24)
    client.ask.assert_called_once()
    assert report["cases"][0]["automated_status"] == "failed"
    assert report["unrun"] == ["firmware"]
