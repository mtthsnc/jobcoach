# Next Action

## Active Milestone

`M7` (Execution)

## Active Task

- Task ID: `M7-CLOSE-001`
- Task: Run final M7 stabilization sweep + release notes and close milestone.
- Why now: `M7-006` is complete with benchmark gate + CI wiring validated, so M7 can be formally closed with a final verification pass, release-note capture, and handoff pointer to M8 planning.

## Exact Next Steps

1. Execute final M7 stabilization validation sequence:
   - `make test`
   - `make validate-openapi`
   - `make migrate-up`
   - `make migrate-down`
   - `JOBCOACH_API_BASE_URL=http://127.0.0.1:8011 make contract-test`
2. Publish M7 closeout notes:
   - summarize shipped M7 scope (`M7-001`..`M7-006`) and quality-gate outcomes,
   - record benchmark/contract validation evidence and environment caveats (sandbox elevated bind for contract tests).
3. Advance planning pointers:
   - mark `M7-CLOSE-001` as `DONE` in `docs/tasklist.md`,
   - move `docs/NEXT_ACTION.md` active pointer to `M8-PLAN-001`.

## Validation Required

- Confirm M7 closeout artifacts are complete and actionable:
  - All M7 tasks are marked `DONE` with evidence.
  - Benchmark and contract quality gates remain green in this environment.
  - Closeout/release-note documentation is recorded.
  - Full validation suite passes in this environment (with documented contract-test port override/elevated run as needed).
  - `docs/work-log.md` records closeout execution evidence and `docs/NEXT_ACTION.md` advances to `M8-PLAN-001`.

## Return Pointer

After `M7-CLOSE-001` is complete, execute `M8-PLAN-001`.
