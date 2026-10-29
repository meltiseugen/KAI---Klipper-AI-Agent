# Typed context and diagnostic evidence

Finding citations carry structured line ranges, file/excerpt scope, evidence
identity, observation time and config revision. Model conclusions use validated
`answer_claims`; `hypotheses` and `missing_evidence` remain separate. Finding
`recovery` contains a deterministic manual playbook when a rule family matches.
See [intelligence quality](intelligence-quality.md) for resolution and trust limits.

Collected diagnostic/configuration context uses `CollectedArtifact` from
`domain/artifacts.py` before it reaches a diagnostic provider or the tool-using
agent. Durable `Evidence` extends that public model with historical-context
formatting. No provider protocol envelopes or hidden reasoning enter this model.
User questions, dialogue and tool arguments retain their existing contracts.

The normalizer removes credentials before hashing or clipping text. JSON
observations are serialized with finite numbers only. An oversized JSON object
becomes an explicitly partial text excerpt; it is never advertised as complete
JSON. Invalid tool observations become unavailable evidence and remain retryable.
Successful repeated tool calls reuse the same observation ID and collection date.

## Artifact fields

| Field | Meaning |
| --- | --- |
| `id` | Backend-generated observation identity; stable across model context, API projection and saved history |
| `kind` | Log, config, status, saved profile, reference, shutdown report or general tool result |
| `label`, `source`, `origin` | Display name, source locator/tool and collection boundary; uploaded labels cannot claim host provenance |
| `observed_at` | UTC collection timestamp, not necessarily the time of an event inside a log |
| `freshness` | `current_snapshot`, `historical`, `saved_configuration`, `user_supplied`, `reference` or `unknown` |
| `status` | `complete`, `partial` or `unavailable` within the collection/excerpt scope |
| `content`, `content_format` | Redacted bounded text or serialized JSON |
| `original_characters` | Normalized text size before clipping; zero can mean unknown in older records |
| `line_basis`, `start_line` | Whether positions refer to a collected excerpt or the original config file; absent positions are not invented |
| `config_revision` | Observed on-disk config revision, when available |
| `citations`, `notes` | Backend source references and limitations |

The collected representation retains at most 16,000 characters of content per
artifact. A complete log artifact is still a bounded collected excerpt, not a
claim that the entire original log was searched. File indexes and clipped tool
results remain explicitly partial. Collector timestamps and IDs survive workflow
state serialization. Legacy records remain readable with unknown provenance and
freshness rather than being promoted to verified current state.

Agent tool results keep their existing observation fields and add `_artifact`
metadata in model requests. Uploaded context and initial config excerpts likewise
carry typed metadata. The compatibility diagnosis/config providers receive typed
artifact collections, including saved profile, config and available runtime data.
Existing context receipts still describe which sources reached a model request;
collection alone does not mean every retained character was sent.

## Additive chat response fields

Both `POST /api/chat` and the final `result` event from `POST /api/chat/stream`
return:

```json
{
  "findings": [{
    "code": "heater_heating_failure",
    "severity": "high",
    "severity_rank": 3,
    "confidence": "high",
    "confidence_scope": "observation",
    "confidence_reason": "The retained excerpt matches this failure signature; the root cause remains unconfirmed.",
    "evidence_ids": ["backend-generated-observation-id"]
  }],
  "evidence_blocks": [{
    "id": "backend-generated-observation-id",
    "kind": "klippy_log",
    "label": "uploaded.log",
    "source": "finding:heater_heating_failure:uploaded.log",
    "origin": "user",
    "freshness": "user_supplied",
    "observed_at": "2026-10-27T12:00:00+00:00",
    "status": "complete",
    "content_format": "text",
    "content": "Collected excerpt line 2502: Heater extruder not heating at expected rate",
    "line_basis": "excerpt",
    "start_line": 2502
  }],
  "evidence_blocks_omitted": 0
}
```

The example omits existing finding fields and some artifact fields for brevity.
`findings`, `source_citations`, response text and action fields remain available.
The new API fields are optional for clients; older responses/records default to
an empty list and zero omitted blocks.

The HTTP projection retains at most 24 unique blocks, with at most 2,000 content
characters per block and four citations of at most 500 excerpt characters each.
Source locators, notes and citation labels/paths are also bounded. Further clipping
marks a block partial and changes clipped JSON to text. Omitted blocks are counted.
Focused finding excerpts are prioritized so failures late in a long log remain
visible even when its general excerpt is clipped. Finding `evidence_ids` link the
focused quote and broader source observations. A broader source may be omitted
from the bounded response; the saved investigation retains its public evidence.

`GET /api/investigations/{id}` continues returning the stored `result.evidence`,
now with the same typed metadata and IDs. JSON/SSE projection does not rewrite
stored observations. Conversation deletion and retention keep their existing
semantics; no new database or printer writes are introduced. Recovery observations
and recalled context are explicitly historical and preserve original dates.

## Severity and confidence

Severity sorts findings by impact: `critical` = 4, `high` = 3, `medium` = 2 and
`low` = 1. The backend derives `severity_rank` from `severity`; a supplied rank
cannot override it. Findings are returned in descending impact order, preserving
discovery order for ties.

Confidence is independent of that rank:

- `high` observation confidence means a retained excerpt matches the reported
  failure signature, or an exact placeholder was observed in config. It does not
  establish current printer state, authentic source origin or a physical cause.
- `medium` observation confidence accompanies conservative static config checks;
  incomplete includes, firmware compatibility and physical wiring still need
  verification.
- `unknown` / `unassessed` is the default for older or otherwise unassessed findings.
  It is not silently upgraded because severity is high.

`confidence_scope` distinguishes `observation`, `hypothesis` and `unassessed`;
`confidence_reason` explains the basis and limit. These are qualitative hints,
not calibrated probabilities. Existing shutdown cause assessments retain their
more specific confidence descriptions and supporting incident observations.
Model prose cannot create trusted finding scores, source references or evidence
blocks; these originate from backend collection and deterministic checks.

## Verification

`test_typed_artifacts.py` covers redaction, clipping, source scope, IDs, snapshot
serialization and focused excerpts. `test_evidence_pipeline.py` exercises cached,
invalid and oversized tool observations, both provider paths, JSON/SSE responses,
rank/confidence separation and saved-history identity. Its HTTP checks use an
in-process server and scripted model. They do not validate a real browser,
live provider answers or live printer behavior.
