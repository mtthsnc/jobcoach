# Next Action

## Active Milestone

`M6` (Product Roadmap)

## Active Task

- Task ID: `M6-002`
- Task: Build deterministic negotiation-context aggregator from offer inputs + interview/feedback/trajectory history.
- Why now: `M6-001` completed the contract/storage foundation, so M6 can now harden deterministic signal generation before strategy/follow-up synthesis.

## Exact Next Steps

1. Add deterministic negotiation-context aggregation module (inputs: candidate offer context + latest trajectory signals + feedback/interview trends).
2. Integrate aggregation output into negotiation plan generation payload under explicit structured fields (`compensation_targets`, leverage/risk signals, evidence links).
3. Add fixture-driven unit tests to lock deterministic ordering/math for identical histories.
4. Extend API/unit/contract tests to assert context fields are stable, reproducible, and schema-valid.
5. Run `make validate-openapi`, `make migrate-up`, `make migrate-down`, `make test`, and `make contract-test`.

## Validation Required

- Confirm planning artifacts are coherent and actionable:
  - Aggregated negotiation-context signals are deterministic on fixed fixtures.
  - Negotiation plan payload remains schema-valid after context integration.
  - Unit/contract suites assert stable signal ordering and numeric bounds.
  - `docs/work-log.md` records M6-002 execution evidence.

## Return Pointer

After `M6-002` is complete, advance pointer to `M6-003`.
