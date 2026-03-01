# Next Action

## Active Milestone

`M8` (Operational Hardening)

## Active Task

- Task ID: `M8-002`
- Task: Add structured request logging with request-id propagation, latency metrics, and sensitive-field redaction policy.
- Why now: `M8-001` auth guardrails are complete, so observability/redaction hardening is the next prerequisite for reliable outbox relay and async worker operations.

## Exact Next Steps

1. Implement structured logging middleware in the gateway:
   - emit method/path/status/request_id/latency_ms for each request,
   - preserve deterministic request-id propagation from `x-request-id` when supplied,
   - ensure logging includes auth failure paths and success paths consistently.
2. Enforce sensitive-field redaction policy in logs:
   - prevent raw payload leakage for high-risk text fields (`cv_text`, story notes, large free-text source values),
   - log bounded/redacted metadata instead of full sensitive text.
3. Align tests/contracts with observability semantics:
   - add/extend unit tests for request-id propagation, latency field presence, and redaction coverage,
   - update contract harness assertions only where externally visible behavior changes.
4. Run validation and record handoff:
   - execute targeted tests plus full gates (`make test`, `make validate-openapi`, migrate up/down, `make contract-test`),
   - append START/END execution evidence in `docs/work-log.md`,
   - move pointer to `M8-003` after acceptance criteria pass.

## Validation Required

- Confirm `M8-002` acceptance criteria:
  - Logs emit deterministic route/method/status/latency/request_id fields.
  - Request IDs propagate from inbound header when present, and generated IDs remain deterministic in envelope/log linkage.
  - Sensitive request fields are redacted/bounded in logs (no raw CV/story free-text leakage).
  - Validation evidence is captured in `docs/work-log.md`.

## Return Pointer

After `M8-002` is complete, execute `M8-003`.
