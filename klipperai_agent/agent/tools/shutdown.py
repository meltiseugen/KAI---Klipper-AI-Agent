from __future__ import annotations

import json
import re
from typing import Any

from pydantic import Field, validator

from klipperai_agent.agent.ports import ShutdownReader
from klipperai_agent.agent.tools.base import Tool, ToolArguments, ToolContext
from klipperai_agent.diagnostics.shutdown import parse_shutdowns
from klipperai_agent.diagnostics.shutdown_assessment import SOURCES, assess_shutdown
from klipperai_agent.domain.evidence import SourceCitation
from klipperai_agent.domain.shutdown import LogExcerpt


class ShutdownArguments(ToolArguments):
    incident_index: int = Field(
        default=0,
        ge=0,
        le=9,
        description="0 is the latest detected incident in the bounded search; choose another index from the returned incident list.",
    )

    @validator("incident_index", pre=True)
    def strict_index(cls, value: Any) -> int:
        if not isinstance(value, int) or isinstance(value, bool):
            raise ValueError("Incident index must be an integer.")
        return value


class ShutdownTool(Tool[ShutdownArguments]):
    name = "investigate_shutdown"
    label = "Investigate MCU communication and timing shutdowns"
    description = (
        "Analyze current/recent rotated Klippy logs and supplied Klippy artifacts for communication, "
        "Timer too close and homing timeouts. Correlate preceding CPU/memory/MCU counters and available "
        "kernel events; return ranked hypotheses, gaps and manual checks. No printer changes."
    )
    arguments_type = ShutdownArguments

    def __init__(self, reader: ShutdownReader) -> None:
        self._reader = reader

    async def execute(self, arguments: ShutdownArguments, context: ToolContext) -> dict[str, Any]:
        logs = await self._reader.read_logs()
        excerpts = logs.excerpts + [
            LogExcerpt(f"supplied:{item.label}", item.content)
            for item in context.artifacts
            if item.kind == "klippy_log"
        ]
        # File order is current then recent rotations; each file's last run first.
        incidents = [
            incident for excerpt in excerpts for incident in reversed(parse_shutdowns(excerpt))
        ]
        # Known timestamps order dated incidents; undated file order is explicitly provisional.
        if incidents and all(item.estimated_unix_time is not None for item in incidents):
            incidents.sort(key=lambda item: item.estimated_unix_time or 0, reverse=True)
        notes = list(logs.notes)
        notes.append(
            "Search is bounded to retained excerpts. Undated incidents use file/run order; latest is provisional. Excerpt line numbers are not original file line numbers."
        )
        if not incidents:
            return {
                "error": "No supported shutdown signature found in the searched excerpts; this does not prove the printer is healthy.",
                "context_notes": notes,
            }
        if arguments.incident_index >= min(len(incidents), 10):
            return {
                "error": "Incident index unavailable.",
                "available_incidents": min(len(incidents), 10),
            }
        incident = incidents[arguments.incident_index]
        host = await self._reader.read_host(incident.estimated_unix_time)
        transports: dict[str, str] = {}
        try:
            config = await context.config()
            for document in config.documents:
                mcu = None
                for line in document.content.splitlines():
                    section = re.match(r"\s*\[([^]]+)\]", line)
                    if section:
                        name = section[1].strip()
                        mcu = (
                            name.replace("mcu ", "", 1)
                            if name == "mcu" or name.startswith("mcu ")
                            else None
                        )
                    elif mcu and re.match(r"\s*canbus_uuid\s*[:=]", line):
                        transports[mcu] = "CAN"
                    elif mcu and re.match(r"\s*serial\s*[:=]", line):
                        transports[mcu] = "serial (USB or UART; confirm device path)"
        except Exception:
            notes.append("Active configuration unavailable; MCU transports unconfirmed.")
        assessments = assess_shutdown(incident, host, transports)
        citations = incident.citations + [
            SourceCitation(
                label=label,
                path=url,
                url=url,
                excerpt="Reference guidance, not evidence of this printer's fault.",
            )
            for label, url in SOURCES.items()
        ]
        quoted_events = {evidence for assessment in assessments for evidence in assessment.evidence}
        seen_events: set[str] = set()
        for event in host.kernel:
            quote = f"{event['unix_time']}: {event['message'][:350]}"
            if quote in quoted_events and quote not in seen_events:
                seen_events.add(quote)
                citations.append(
                    SourceCitation(
                        label="Kernel event near estimated shutdown",
                        path="shutdown:kernel",
                        excerpt=f"{event['unix_time']}: {event['message'][:500]}",
                    )
                )
        if host.history.get("sample_count"):
            citations.append(
                SourceCitation(
                    label="Recorded host history near estimated shutdown",
                    path="shutdown:host-history",
                    excerpt=json.dumps(host.history.get("pre_stop_summary", {}))[:2000],
                )
            )
        context.citations.extend(citations)
        report: dict[str, Any] = {
            "incident": incident.model_dump(),
            "available_incidents": [
                {
                    "index": index,
                    "source": item.source,
                    "message": item.message[:160],
                    "estimated_unix_time": item.estimated_unix_time,
                }
                for index, item in enumerate(incidents[:10])
            ],
            "assessments": [item.model_dump() for item in assessments[:8]],
            "configured_transports": transports,
            "current_host": host.current,
            "historical_host": host.history,
            "context_notes": notes
            + host.notes
            + [
                "sysload is one-minute load average, not CPU percent; cputime is cumulative Klippy CPU seconds. memavail is KiB. Historical process samples require the separately enabled host flight recorder.",
                "Kernel correlation uses an estimated wall time from the same run's Start printer/Stats or timeout records. Coincidence does not prove causation; current readings cannot explain an earlier stop.",
                "Do not increase safety timeouts, disable protections or change acceleration solely on the shutdown message. Proposed fixes require manual review and a supervised verification.",
            ],
            "truncated": any(excerpt.partial for excerpt in excerpts)
            or len(incidents) > 10
            or len(assessments) > 8,
        }
        history_samples = report["historical_host"].get("samples", [])
        while len(json.dumps(report, ensure_ascii=False)) > 14000 and history_samples:
            history_samples.pop(0)
            report["historical_host"]["truncated"] = True
            report["truncated"] = True
        report["truncated"] = report["truncated"] or bool(host.history.get("truncated"))
        # Keep structured evidence usable under the registry's default 16k result budget.
        while (
            len(json.dumps(report, ensure_ascii=False)) > 14000 and len(report["assessments"]) > 1
        ):
            report["assessments"].pop()
            report["truncated"] = True
        report["omitted_assessments"] = len(assessments) - len(report["assessments"])
        return report
