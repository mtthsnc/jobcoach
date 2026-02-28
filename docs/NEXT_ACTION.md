# Next Action

## Active Milestone

`M5` (Product Roadmap)

## Active Task

- Task ID: `M5-005`
- Task: Add candidate progress dashboard endpoint with competency trend cards and readiness signals.
- Why now: `M5-004` versioned trajectory persistence is complete, so dashboard reads can safely use stable trajectory generations plus longitudinal trend summaries.

## Exact Next Steps

1. Add dashboard endpoint contract + handler for candidate progress view composed from progress summaries and latest trajectory version.
2. Build deterministic read-model assembly for top-improving/top-risk competencies, readiness signals, and recent trajectory metadata.
3. Reuse trajectory version metadata (`version`, supersedes linkage) to expose latest-plan context safely.
4. Add unit/contract tests for deterministic sorting, empty-history behavior, and schema-valid dashboard payloads.
5. Update planning docs to mark `M5-005` complete and move pointer to `M5-006`.

## Validation Required

- Confirm quality gates remain green:
  - `make test`
  - `make validate-openapi`
  - `make migrate-up`
  - `make migrate-down`
  - `make contract-test`

## Return Pointer

After `M5-005` is complete, execute `M5-006`.
