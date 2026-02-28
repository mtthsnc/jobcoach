# Next Action

## Active Milestone

`M5` (Product Roadmap)

## Active Task

- Task ID: `M5-003`
- Task: Implement trajectory milestone + weekly-plan generator from trend metrics and target-role competency gaps.
- Why now: `M5-002` deterministic progress aggregation is complete, so trajectory generation can now consume stable baseline/current/delta metrics.

## Exact Next Steps

1. Replace static trajectory milestones and weekly actions with generator logic derived from aggregated trend metrics and competency deltas.
2. Incorporate target-role gap emphasis so top-risk competencies influence milestone priority and weekly action sequencing.
3. Enforce deterministic generation behavior (stable ordering, bounded horizon, repeatable outputs for fixed inputs).
4. Add unit/contract tests asserting schema validity, date ordering, and evidence-linked action generation from fixed trend fixtures.
5. Update planning docs to mark `M5-003` complete and move pointer to `M5-004`.

## Validation Required

- Confirm quality gates remain green:
  - `make test`
  - `make validate-openapi`
  - `make migrate-up`
  - `make migrate-down`
  - `make contract-test`

## Return Pointer

After `M5-003` is complete, execute `M5-004`.
