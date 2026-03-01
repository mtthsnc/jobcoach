# M7 Release Notes

Date (UTC): `2026-03-01`
Milestone: `M7` (Taxonomy normalization and evaluation-ops orchestration)
Closeout Task: `M7-CLOSE-001`

## Scope Completed

- `M7-001`: Implemented `POST /taxonomy/normalize` with deterministic mapped/unmapped term outputs and mapping persistence semantics.
- `M7-002`: Expanded eval-run orchestration contracts/storage for suite catalog coverage and idempotent run requests.
- `M7-003`: Implemented `POST /evals/run` orchestration flow with deterministic queued->running->terminal transitions and metrics/error capture.
- `M7-004`: Implemented `GET /evals/{eval_run_id}` retrieval with schema-valid lifecycle status/metrics/error payloads.
- `M7-005`: Added eval-run outbox lifecycle events (`queued`, `succeeded`, `failed`) with deterministic IDs and retry-safe dedup semantics.
- `M7-006`: Added eval orchestration benchmark gate and CI artifact wiring.

## Final Validation Sweep

- `TMPDIR=/Users/maha/dev/jobcoach/.tmp PYTHONDONTWRITEBYTECODE=1 make test` -> pass.
- `make validate-openapi` -> pass (offline structural checks path).
- `MIGRATE_DB_PATH=.tmp/m7-close-migrate-up.sqlite3 make migrate-up` -> pass.
- `MIGRATE_DB_PATH=.tmp/m7-close-migrate-down.sqlite3 make migrate-down` -> pass.
- `TMPDIR=/Users/maha/dev/jobcoach/.tmp JOBCOACH_API_BASE_URL=http://127.0.0.1:8011 make contract-test` -> initial sandbox bind failure, then pass on elevated rerun.

## Quality Gates in Effect

- Unit + contract test suites.
- OpenAPI structural validation.
- Migration up/down smoke validation.
- Benchmark gates enforced via `make test`:
  - Extraction quality
  - Candidate parse quality
  - Interview relevance quality
  - Feedback quality
  - Trajectory quality
  - Negotiation quality
  - Eval orchestration quality

## Known Environment Caveats

- In this sandbox, contract tests can fail without elevated execution due local socket bind restrictions (`PermissionError: [Errno 1] Operation not permitted`).
- For deterministic local contract validation in this environment, use `JOBCOACH_API_BASE_URL=http://127.0.0.1:8011`.
