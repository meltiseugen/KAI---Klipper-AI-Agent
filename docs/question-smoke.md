# Live question smoke suite

Page readiness does not establish answer quality. This suite exercises the real
installed KAI chat API, saved provider, starting context, tool loop, SSE response
and public evidence. It never sends printer commands or changes configuration.
It creates new investigation threads and preserves their answers for review.

Run from a development checkout using an existing SSH tunnel or trusted LAN URL:

```sh
# List the questions and human acceptance criteria without making requests.
python -m tools.smoke_questions

# Uses the server's saved API key and provider credits. No key is passed here.
python -m tools.smoke_questions --live \
  --base-url http://127.0.0.1:8080/kai \
  --request-budget 24 --output .local/question-smoke/report.json

# Reproduce just the reported component inventory failure.
python -m tools.smoke_questions --live --case components \
  --output .local/question-smoke/components.json
```

The six questions cover component inventory, firmware/version, current print
status, the START_PRINT definition, incident uncertainty and refusal to execute
printer actions. Cases and acceptance criteria live in `tools/question_smoke.py`.
Each question starts a fresh thread; ordinary configured cross-chat evidence
retrieval still applies. Existing user threads and settings are preserved.

The request budget stops **between questions** after their reported completed
model requests reach the limit. An individual question can cross that threshold;
its normal server step/time/tool limits remain in force. The harness does not
change provider settings or retry failed/ambiguous network requests. HTTP errors,
rate limits and incomplete SSE streams fail the run. Reports are written after
each question so earlier results survive later failures. Keep these private
reports under ignored `.local/`; they can contain redacted printer evidence.

Mechanical checks reject limit/error outcomes, empty answers, absent completed
provider requests, missing grounded claims for printer-specific questions,
unestablished current connectivity and unexpected configuration proposals.
Exit zero means those checks passed, **not** that the prose is correct.
Every report marks human review as required. Review each answer against its
retained evidence and the listed criteria: invented hardware, mismatched sources,
historical/current confusion and unsupported causal claims remain failures even
if keywords or the mechanical checks pass. Record the review and relevant gaps.

For browser acceptance, start at the actual Mainsail/OctoEverywhere portal, open
KAI, submit a representative question and inspect the answer, evidence, model
usage and connection indicator. API success over an SSH tunnel does not establish
remote proxy/browser streaming behavior. Report offline tests, live provider/API
results, browser checks and printer-state preservation separately.
