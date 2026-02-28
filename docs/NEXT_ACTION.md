# Next Action

## Active Milestone

`M5` (Product Roadmap)

## Active Task

- Task ID: `M5-006`
- Task: Add trajectory quality benchmark + threshold gates for CI/local.
- Why now: `M5-005` dashboard read-model outputs are now deterministic and version-aware, so benchmark thresholds can lock regression behavior for trajectory quality and trend-card stability.

## Exact Next Steps

1. Implement trajectory quality benchmark runner with deterministic fixture scoring over trend metrics, readiness signals, and trajectory/dashboard consistency.
2. Add benchmark fixtures that cover improving, declining, and empty-history candidates plus versioned trajectory regeneration context.
3. Wire threshold gates into `make test`/CI so regressions in trend math or trajectory quality fail deterministically.
4. Add unit coverage for benchmark metric calculations and threshold-failure reporting.
5. Update planning docs to mark `M5-006` complete and advance to the next milestone planning task.

## Validation Required

- Confirm quality gates remain green:
  - `make test`
  - `make validate-openapi`
  - `make migrate-up`
  - `make migrate-down`
  - `make contract-test`

## Return Pointer

After `M5-006` is complete, execute the next milestone planning task.
