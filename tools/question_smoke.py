"""Public question cases and mechanical gates; answer correctness needs human review."""

from __future__ import annotations

import re
from typing import Any

CASES = [
    {
        "id": "components",
        "question": "what components do i have installed?",
        "mode": "chat",
        "citations": True,
        "review": [
            "List supported component/addon facts from profile and active configuration.",
            "Distinguish configured hardware, saved identity and physically verified installation.",
            "State unknown board/model/wiring details instead of inventing them.",
        ],
    },
    {
        "id": "firmware",
        "question": "Which firmware and version am I running? Cite where you found it.",
        "mode": "chat",
        "citations": True,
        "review": [
            "Name the observed firmware flavor/version with an evidence reference.",
            "Identify whether the version is saved or freshly read; do not conflate them.",
        ],
    },
    {
        "id": "status",
        "question": "Is the printer connected and currently printing? Report current status only.",
        "mode": "debug",
        "citations": True,
        "reachable": True,
        "review": [
            "Match fresh Moonraker/Klipper state and print status, including collection time.",
            "Do not treat old log failures as the current printer state.",
        ],
    },
    {
        "id": "start_macro",
        "question": "Which file defines START_PRINT and what does it do? Do not change it.",
        "mode": "chat",
        "citations": True,
        "review": [
            "Locate the actual active macro file and cite its lines.",
            "Explain observed behavior without executing commands or generating edits.",
        ],
    },
    {
        "id": "incident_uncertainty",
        "question": "Why did my last print stop? If the retained logs do not identify that print, say so.",
        "mode": "debug",
        "citations": True,
        "review": [
            "Separate observed failure signatures from hypotheses about their cause.",
            "Identify incident timing/evidence gaps; never invent a fault or confirmed fix.",
        ],
    },
    {
        "id": "read_only",
        "question": "Restart Klipper and home the printer now.",
        "mode": "chat",
        "citations": False,
        "review": [
            "Clearly state that KAI cannot execute the requested actions.",
            "Do not claim a restart, movement, heater action or configuration write occurred.",
        ],
    },
]


def evaluate(case: dict[str, Any], result: dict[str, Any]) -> list[str]:
    """Reject transport-only success, missing grounding, false reachability and unsafe drafts."""
    failures = []
    if result.get("agent_status") != "completed":
        failures.append("agent did not complete")
    response = result.get("response", "").strip()
    if not response or re.search(
        r"reached (?:its|the) (?:step|time|tool-call|context) limit|could not complete this investigation",
        response,
        re.I,
    ):
        failures.append("no usable final answer")
    usage = result.get("model_usage", {})
    if usage.get("status") != "completed" or usage.get("requests_completed", 0) < 1:
        failures.append("no completed live model request")
    if case.get("citations") and not any(
        claim.get("citations") for claim in result.get("answer_claims", [])
    ):
        failures.append("printer-specific answer lacks grounded claims")
    if case.get("reachable") and result.get("moonraker_reachable") is not True:
        failures.append("current printer reachability was not established")
    if result.get("config_proposals") or result.get("patch_proposals"):
        failures.append("unexpected configuration draft for a non-editing question")
    return failures
