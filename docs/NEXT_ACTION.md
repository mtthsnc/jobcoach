# Next Action

## Active Milestone

`M6` (Product Roadmap)

## Active Task

- Task ID: `M6-004`
- Task: Implement post-interview follow-up planner (thank-you draft, recruiter cadence, outcome branches).
- Why now: `M6-003` introduced deterministic negotiation strategy structures; follow-up planning now needs the same deterministic, schema-backed planning layer.

## Exact Next Steps

1. Add deterministic follow-up planner module that emits thank-you draft guidance, recruiter touchpoint cadence, and branch actions from negotiation context + strategy signals.
2. Integrate follow-up planner output into `NegotiationPlan` payload with explicit schema fields and deterministic ordering of actions.
3. Add fixture-driven unit tests to lock branch selection, day-offset bounds, and deterministic follow-up content for fixed contexts.
4. Extend API/unit/contract tests to assert follow-up plan fields are stable across regeneration/idempotent create flows and remain schema-valid.
5. Run `make validate-openapi`, `make migrate-up`, `make migrate-down`, `make test`, and `make contract-test`.

## Validation Required

- Confirm planning artifacts are coherent and actionable:
  - Follow-up planning output is deterministic for fixed context fixtures.
  - Negotiation plan payload remains schema-valid after follow-up plan integration.
  - Unit/contract suites assert stable branch selection, day offsets, and action ordering.
  - `docs/work-log.md` records M6-004 execution evidence.

## Return Pointer

After `M6-004` is complete, advance pointer to `M6-005`.
