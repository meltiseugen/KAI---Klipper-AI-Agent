"""A fixed, user-triggered provider response probe containing no printer data."""

import json

from klipperai_agent.domain.investigation import utc_now
from klipperai_agent.providers.responses import ResponsesClient


async def probe_provider(client: ResponsesClient | None) -> dict:
    report = {
        "checked_at": utc_now(),
        "kind": "live_provider",
        "passed": False,
        "printer_data_sent": False,
        "message": "A live tool-using provider is not configured.",
    }
    if client is None:
        return report
    try:
        output = await client.create(
            input="Return a JSON object with ok set to true.",
            tools=[],
            max_output_tokens=512,
            text={
                "format": {
                    "type": "json_schema",
                    "name": "provider_probe",
                    "strict": True,
                    "schema": {
                        "type": "object",
                        "properties": {"ok": {"type": "boolean"}},
                        "required": ["ok"],
                        "additionalProperties": False,
                    },
                }
            },
        )
        content = "".join(
            str(part.get("text", ""))
            for item in output
            if item.get("type") == "message"
            for part in item.get("content", [])
            if part.get("type") == "output_text"
        )
        report["passed"] = json.loads(content) == {"ok": True}
        report["message"] = (
            "Live response and structured-output parsing passed."
            if report["passed"]
            else "Provider returned an unexpected response."
        )
    except Exception:
        report["message"] = (
            "Live response probe failed; check provider access, budget and structured-output support."
        )
    return report
