# Intelligence quality

The agent selects a response contract locally for each request. This adds no
tools, permissions or model classification call. Chat and Debug still control
starting evidence; the workflow controls the answer's structure.

| Workflow | Output and constraints |
| --- | --- |
| General | Direct answer, next actions, cited claims and missing evidence; no config drafts |
| Diagnosis | Observations, separately labeled hypotheses, missing evidence and manual checks; no config drafts |
| Config explanation | Existing config locations/explanations, citations and on-disk/reference/unavailable scope; no drafts |
| Config draft | Requested snippets with assumptions and warnings; application-owned static review follows |

`agent/response_contracts.py` owns selection, guidance, Pydantic v1 validation and
closed JSON schemas. The Responses adapter sends the selected schema through
`text.format` with `strict: true`. The runner also validates locally. Invalid
output or fabricated citation references get a bounded repair turn within the
existing step/time budgets. It never silently switches schemas or grants extra
capabilities after an error. The legacy single-pass compatibility providers retain
their separate diagnosis/config contracts and JSON-mode transport.

Schemas contain concise public conclusions and evidence gaps. They do not request
or persist hidden model reasoning. Existing read-only tool, deadline, context,
proposal-review and credential policies continue to apply.

## Deterministic checks and recovery

`diagnostics/signatures.py` holds runtime failure signatures;
`diagnostics/rules.py` produces ranked observations. Supplied artifacts run through
the rules before the first model call, including in Chat, without fetching host
logs. Debug and diagnostic tools also check collected host evidence. Comments,
config snippets and logged config dumps do not become runtime faults.

Additional signatures cover cold extrusion, excessive extrusion cross-section,
excessive extrusion-only distance, absent homing state and terminal probe sampling
tolerance failures. A retry notice alone is not a terminal sampling failure. A
match establishes what the retained log reports, not its physical cause or current
state.

`diagnostics/playbooks.py` selects nine manual recovery families from finding codes:
MCU communication/scheduling, thermal protection, homing/probe state, probe
repeatability, TMC drivers, extrusion guards, motion limits, config startup and
host services. Each supplies required evidence, ordered manual checks,
verification criteria, stop conditions and reference documentation. Playbooks
appear in agent finding cards and remain available in saved
history. Unknown codes do not acquire a speculative playbook. No plan executes
commands, changes settings, disables protections or restarts anything.

## Structured citations

Findings contain `citations`; model-generated public conclusions become
`answer_claims` after reference validation. A model reference contains only an
`evidence_id` and inclusive `start_line` / `end_line` range. Both lines set to zero
select source citations already attached by a trusted collector/tool. The model
cannot provide a trusted path, quote, timestamp or revision.

The resolver checks retained evidence, availability, line basis, text format and
range bounds, and rejects clipped markers and oversized quotes. It derives source
paths, exact excerpts, config section, collection time and revision itself. Log
excerpt lines remain excerpt positions; they never become invented original-file
line numbers. References to structured tool observations must use that tool's
retained source citations rather than line numbers in serialized JSON.

JSON/SSE responses and stored turns retain claims, hypotheses, gaps, finding
citations and recovery plans. The browser renders text safely, preserves those
fields through history restoration, distinguishes file/excerpt lines and
deduplicates sources. Older saved turns remain readable through additive defaults.

Citation validation establishes traceability to retained text. It does not prove
that the text is true or that a model's interpretation or causal claim is correct.
Collection time dates the observation, not every event in a historical log.

## Validation and references

Automated tests cover signature positives and near misses, workflow selection,
closed schemas, provider request bodies, bounded repair, citation bounds and exact
quotes, config sections/revisions, API projection, persistence and browser history
rendering. Fixtures do not establish live provider quality or printer behavior.

Protocol: [OpenAI Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs).
Signature provenance: upstream Klipper
[extrusion guards](https://github.com/Klipper3d/klipper/blob/master/klippy/kinematics/extruder.py),
[homing guard](https://github.com/Klipper3d/klipper/blob/master/klippy/kinematics/cartesian.py)
and [probe sampling](https://github.com/Klipper3d/klipper/blob/master/klippy/extras/probe.py),
checked 2026-10-27. These describe upstream messages; they do not prove compatibility
with every installed version or firmware fork.
