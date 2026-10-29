from __future__ import annotations

from collections.abc import Iterator

from klipperai_agent.config.models import ConfigSnapshot
from klipperai_agent.diagnostics.playbooks import recovery_playbook
from klipperai_agent.diagnostics.signatures import RUNTIME_SIGNATURES
from klipperai_agent.domain.evidence import (
    ArtifactInput,
    IssueFinding,
    SourceCitation,
    severity_rank,
)


def diagnostic_lines(content: str) -> Iterator[tuple[int, str]]:
    """Keep excerpt positions while excluding comments and Klipper config dumps."""
    in_config = False
    for number, raw in enumerate(content.splitlines(), 1):
        line = raw.strip()
        if line == "===== Config file =====":
            in_config = True
            continue
        if in_config:
            if line == "=======================":
                in_config = False
            continue
        if line and not line.startswith(("#", ";")):
            yield number, line


class RuleEngine:
    _PATTERNS = RUNTIME_SIGNATURES

    def analyze(
        self,
        artifacts: list[ArtifactInput],
        *,
        config_snapshot: ConfigSnapshot | None = None,
    ) -> list[IssueFinding]:
        findings: list[IssueFinding] = []
        seen_codes: set[tuple[str, str, str]] = set()

        for artifact in artifacts:
            if artifact.kind == "config_snippet":
                continue
            lines = list(diagnostic_lines(artifact.content))
            for code, pattern, severity, summary, fix in self._PATTERNS:
                for number, line in lines:
                    match = pattern.search(line)
                    if not match:
                        continue

                    component = match.groupdict().get("component", "")
                    key = (code, artifact.label, component.casefold())
                    if key in seen_codes:
                        continue
                    seen_codes.add(key)

                    # These positions refer to the collected excerpt, not the original log.
                    excerpt = line[max(0, match.start() - 80) : match.start() + 1000]
                    detail = f" Reported component: {component}." if component else ""
                    findings.append(
                        IssueFinding(
                            code=code,
                            severity=severity,
                            source=artifact.label,
                            summary=summary + detail,
                            evidence=f"Collected excerpt line {number}: {excerpt}",
                            proposed_fix=fix,
                            citations=[
                                SourceCitation(
                                    label=artifact.label,
                                    path=artifact.label,
                                    line_number=number,
                                    end_line=number,
                                    line_basis="excerpt",
                                    excerpt=excerpt,
                                )
                            ],
                            recovery=recovery_playbook(code),
                            confidence="high",
                            confidence_scope="observation",
                            confidence_reason="The retained excerpt matches this failure signature. This supports the reported observation, not a confirmed root cause or current fault.",
                        )
                    )

        if config_snapshot is not None:
            findings.extend(self._analyze_config_snapshot(config_snapshot))

        findings.sort(key=lambda finding: self._severity_rank(finding.severity), reverse=True)
        return findings

    @staticmethod
    def _severity_rank(severity: str) -> int:
        return severity_rank(severity)

    def _analyze_config_snapshot(self, config_snapshot: ConfigSnapshot) -> list[IssueFinding]:
        findings: list[IssueFinding] = []

        for placeholder in config_snapshot.placeholders[:8]:
            section_detail = f" in section [{placeholder.section}]" if placeholder.section else ""
            option_detail = f" for option '{placeholder.option}'" if placeholder.option else ""
            findings.append(
                IssueFinding(
                    code="config_placeholder_value",
                    severity="high",
                    source=f"{placeholder.path}:{placeholder.line_number}",
                    summary=(
                        f"Placeholder value {placeholder.value} is still active{section_detail}{option_detail}, "
                        "which can prevent Klipper from loading the config."
                    ),
                    evidence=placeholder.line_text,
                    citations=[
                        SourceCitation(
                            label=placeholder.path,
                            path=placeholder.path,
                            line_number=placeholder.line_number,
                            end_line=placeholder.line_number,
                            section=placeholder.section,
                            line_basis="file",
                            excerpt=placeholder.line_text,
                        )
                    ],
                    recovery=recovery_playbook("config_placeholder_value"),
                    confidence="high",
                    confidence_scope="observation",
                    confidence_reason="The placeholder is present in collected on-disk configuration; loaded firmware state and physical wiring remain unverified.",
                    proposed_fix=(
                        f"Replace {placeholder.value} with the real hardware value in "
                        f"{placeholder.path}:{placeholder.line_number} and restart Klipper."
                    ),
                )
            )

        return findings
