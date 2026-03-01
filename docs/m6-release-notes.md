# M6 Release Notes

Date (UTC): `2026-03-01`
Milestone: `M6` (Negotiation and post-interview assistant)
Closeout Task: `M6-CLOSE-001`

## Scope Completed

- `M6-001`: Added `NegotiationPlan` contracts, endpoints, and storage migration.
- `M6-002`: Added deterministic negotiation-context aggregation from offer + history signals.
- `M6-003`: Added deterministic negotiation strategy generation (`anchor_band`, concession ladder, objection playbook).
- `M6-004`: Added deterministic follow-up planning (`thank_you_note`, recruiter cadence, outcome branches).
- `M6-005`: Added versioned negotiation persistence semantics (`version`, `supersedes_negotiation_plan_id`, optimistic `expected_version`).
- `M6-006`: Added negotiation/follow-up quality benchmark gate and CI wiring.

## Final Validation Sweep

- `PYTHONDONTWRITEBYTECODE=1 make test` -> pass.
- `make validate-openapi` -> pass.
- `MIGRATE_DB_PATH=.tmp/m6-close-migrate-up.sqlite3 make migrate-up` -> pass.
- `MIGRATE_DB_PATH=.tmp/m6-close-migrate-down.sqlite3 make migrate-down` -> pass.
- `TMPDIR=/Users/maha/dev/jobcoach/.tmp JOBCOACH_API_BASE_URL=http://127.0.0.1:8011 make contract-test` -> pass (elevated execution required in this sandbox).

## Quality Gates in Effect

- Unit + contract test suites.
- OpenAPI structural validation.
- Migration up/down smoke validation.
- Benchmark gates now enforced via `make test`:
  - Extraction quality
  - Candidate parse quality
  - Interview relevance quality
  - Feedback quality
  - Trajectory quality
  - Negotiation quality

## Known Environment Caveats

- In this sandbox, contract tests may fail without elevated execution due local socket bind restrictions (`PermissionError: [Errno 1] Operation not permitted`).
- For deterministic local contract validation in this environment, use `JOBCOACH_API_BASE_URL=http://127.0.0.1:8011`.
