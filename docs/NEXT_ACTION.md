# Next Action

## Active Milestone

`M5` (Product Roadmap)

## Active Task

- Task ID: `M5-001`
- Task: Add `TrajectoryPlan` orchestration contract endpoints and storage migration.
- Why now: `M5-PLAN-001` is complete, and M5 execution should begin with contract/storage foundations for trajectory planning.

## Exact Next Steps

1. Extend OpenAPI for trajectory-plan create/get endpoints and request/response schemas (including idempotency/error semantics).
2. Add SQL migration(s) for `trajectory_plans` persistence with idempotency support and retrieval indexes.
3. Implement API gateway handler + repository flows for create/get with deterministic response envelopes.
4. Add contract/unit coverage for happy path, validation failures, idempotency replay/conflict, and not-found retrieval.
5. Update planning docs to mark `M5-001` complete and move pointer to `M5-002`.

## Validation Required

- Confirm quality gates remain green:
  - `make test`
  - `make validate-openapi`
  - `make migrate-up`
  - `make migrate-down`
  - `make contract-test`

## Return Pointer

After `M5-001` is complete, execute `M5-002`.
