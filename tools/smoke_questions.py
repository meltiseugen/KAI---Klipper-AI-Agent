"""Run bounded live questions against an installed KAI API using its saved provider.

Dry-run by default. --live sends printer context to the configured model and uses
provider credits. Reports contain public answers/evidence, never API keys or hidden reasoning.
"""

from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from tools.question_smoke import CASES, evaluate


class KAIClient:
    def __init__(self, base_url: str, timeout: float = 225) -> None:
        url = urllib.parse.urlsplit(base_url)
        if url.scheme not in {"http", "https"} or not url.hostname or url.username or url.password:
            raise ValueError("Use an HTTP(S) KAI base URL without embedded credentials.")
        self.base = base_url.rstrip("/") + "/api/"
        self.origin = urllib.parse.urlunsplit((url.scheme, url.netloc, "", "", ""))
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        self.timeout = timeout

    def request(self, path: str, body: dict | None = None):
        request = urllib.request.Request(
            self.base + path,
            data=None if body is None else json.dumps(body).encode(),
            headers={"Content-Type": "application/json", "Origin": self.origin},
        )
        return self.opener.open(request, timeout=self.timeout)

    def session(self) -> str:
        with self.request("ui-sessions", {}) as response:
            return json.load(response)["session_id"]

    def ask(self, session: str, case: dict) -> tuple[dict, list[dict]]:
        events = []
        payload = {
            "session_id": session,
            "thread_id": str(uuid4()),
            "message": case["question"],
            "mode": case["mode"],
        }
        # Heartbeats keep the connection alive; disconnecting cancels the server-side run.
        with self.request("chat/stream", payload) as response:
            name, data = "", []
            for raw in response:
                line = raw.decode("utf-8").rstrip("\r\n")
                if line.startswith("event:"):
                    name = line[6:].strip()
                elif line.startswith("data:"):
                    data.append(line[5:].lstrip())
                elif not line and data:
                    value = json.loads("\n".join(data))
                    if name == "result":
                        return value, events
                    if name == "error":
                        raise RuntimeError(value.get("message", "KAI stream failed"))
                    events.append({"event": name, "data": value})
                    name, data = "", []
        raise RuntimeError("KAI stream ended without a final result")


def run_cases(client: KAIClient, cases: list[dict], output: Path, request_budget: int) -> dict:
    report: dict[str, Any] = {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "base_url": client.base.removesuffix("/api/"),
        "request_budget": request_budget,
        "budget_scope": "Stops between questions; each question retains the server's run limits.",
        "requests_completed": 0,
        "cases": [],
        "unrun": [],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    session = client.session()
    for index, case in enumerate(cases):
        if report["requests_completed"] >= request_budget:
            report["unrun"] = [item["id"] for item in cases[index:]]
            break
        started = time.monotonic()
        entry = {"id": case["id"], "question": case["question"], "review_criteria": case["review"]}
        try:
            result, events = client.ask(session, case)
            entry.update(result=result, stream_events=events, failures=evaluate(case, result))
            report["requests_completed"] += result.get("model_usage", {}).get(
                "requests_completed", 0
            )
        except (OSError, ValueError, RuntimeError) as exc:
            entry["failures"] = [f"Request failed: {type(exc).__name__}: {exc}"]
            # Do not blindly retry: a failed connection may already have used provider credits.
            report["unrun"] = [item["id"] for item in cases[index + 1 :]]
        entry.update(
            seconds=round(time.monotonic() - started, 2),
            automated_status="failed" if entry["failures"] else "passed",
            human_review="required",
        )
        report["cases"].append(entry)
        output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"{case['id']}: {entry['automated_status']} ({entry['seconds']}s)", flush=True)
        if "result" not in entry:
            break
    report["completed_at"] = datetime.now(timezone.utc).isoformat()
    output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8080/kai")
    parser.add_argument("--case", action="append", choices=[item["id"] for item in CASES])
    parser.add_argument("--output", type=Path, default=Path(".local/question-smoke/report.json"))
    parser.add_argument("--request-budget", type=int, default=24)
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args()
    if not 1 <= args.request_budget <= 48:
        parser.error("--request-budget must be between 1 and 48")
    cases = [case for case in CASES if not args.case or case["id"] in args.case]
    if not args.live:
        print(json.dumps(cases, indent=2))
        print(
            "Dry run. Add --live to use the installed provider. No printer commands are executed."
        )
        return 0
    report = run_cases(KAIClient(args.base_url), cases, args.output, args.request_budget)
    return int(bool(report["unrun"]) or any(case["failures"] for case in report["cases"]))


if __name__ == "__main__":
    raise SystemExit(main())
