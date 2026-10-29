# Printer failure examples

These short **synthetic** excerpts are small developer regression artifacts, not
real incident captures or verified physical diagnoses. `cases.json` records the
expected observations and example agent questions. The negative control checks
that normal startup does not become a failure report.

`tests/test_failure_examples.py` replays them through the actual evidence rules,
checks source citations and confirms the examples remain unchanged. The LLM can
use such findings as evidence; a matching log line does not determine a physical
cause or justify changing safety limits. Real printer acceptance must separately
verify automatic collection, model investigation and manual recovery advice.

Use disposable fixture directories when developing collection tests. Do not copy
these logs over a live printer's logs or config. The web UI needs no attachment or
paste workflow: the agent reads configured printer logs and config itself.

The sourced incident corpus in `tests/fixtures/shutdown/` complements these examples
with provenance and USB/CAN shutdown replay checks.
