# Next Action

## Active Milestone

`M7` (Execution)

## Active Task

- Task ID: `M7-006`
- Task: Add eval-orchestration quality benchmark + CI/local threshold gate.
- Why now: `M7-005` is complete, so the remaining critical-path dependency for M7 is a deterministic benchmark gate that catches eval-run orchestration regressions (status transitions, idempotency behavior, metrics/event integrity).

## Exact Next Steps

1. Implement eval orchestration benchmark runner and fixtures:
   - validate deterministic queued/running/terminal transition persistence for eval runs,
   - validate replay/conflict idempotency semantics across repeated create requests,
   - validate lifecycle outbox event integrity (`eval_run.queued`, terminal event payload consistency).
2. Define thresholded metrics/report contract for M7 quality gate:
   - include transition correctness and idempotency correctness metrics,
   - include lifecycle event emission correctness metrics,
   - emit deterministic report artifacts for CI/local runs.
3. Wire benchmark gate into local/CI validation flow:
   - ensure `make test` (or delegated quality target) fails when thresholds are not met,
   - add deterministic unit coverage for benchmark math/report structure.
4. Run validation sequence:
   - `make test`
   - `make validate-openapi`
   - `make migrate-up`
   - `make migrate-down`
   - `JOBCOACH_API_BASE_URL=http://127.0.0.1:8011 make contract-test`

## Validation Required

- Confirm M7-006 implementation artifacts are complete and actionable:
  - Eval-orchestration benchmark report is deterministic and thresholded.
  - Benchmark covers transition correctness, idempotency behavior, and lifecycle outbox integrity.
  - CI/local gate fails on benchmark regressions.
  - Full validation suite passes in this environment (with documented contract-test port override/elevated run as needed).
  - `docs/work-log.md` records execution evidence and `docs/NEXT_ACTION.md` advances to `M7-CLOSE-001`.

## Return Pointer

After `M7-006` is complete, execute `M7-CLOSE-001`.
