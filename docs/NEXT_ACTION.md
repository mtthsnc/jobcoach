# Next Action

## Active Milestone

`M7` (Execution)

## Active Task

- Task ID: `M7-005`
- Task: Emit outbox lifecycle events for eval runs (queued/succeeded/failed) with retry-safe publication semantics.
- Why now: `M7-004` is complete, so the next critical-path dependency is publishing eval-run lifecycle events needed by downstream automation and observability consumers.

## Exact Next Steps

1. Implement eval-run lifecycle outbox persistence in the API gateway/repository flow:
   - enqueue `eval_run.queued` when `POST /v1/evals/run` creates a new run,
   - enqueue `eval_run.succeeded` and `eval_run.failed` on terminal transitions,
   - avoid duplicate outbox event emission on idempotent replay.
2. Define deterministic event payload contract for each lifecycle event:
   - include `eval_run_id`, `suite`, `status`, and stable timestamp fields,
   - include metrics/error payload for terminal events,
   - ensure retry-safe idempotency semantics at persistence boundary.
3. Add/extend unit + contract tests for lifecycle outbox events:
   - created-run enqueue behavior,
   - terminal transition enqueue behavior (succeeded and failed),
   - replay/conflict semantics do not duplicate lifecycle events.
4. Run validation sequence:
   - `make test`
   - `make validate-openapi`
   - `make migrate-up`
   - `make migrate-down`
   - `JOBCOACH_API_BASE_URL=http://127.0.0.1:8011 make contract-test`

## Validation Required

- Confirm M7-005 implementation artifacts are complete and actionable:
  - `POST /v1/evals/run` and terminal transitions emit deterministic eval-run outbox lifecycle events.
  - Event persistence is retry-safe and idempotency replay does not duplicate lifecycle events.
  - Lifecycle event payloads remain schema-consistent and deterministic for fixed inputs.
  - Full validation suite passes in this environment (with documented contract-test port override/elevated run as needed).
  - `docs/work-log.md` records execution evidence and `docs/NEXT_ACTION.md` advances to `M7-006`.

## Return Pointer

After `M7-005` is complete, execute `M7-006`.
