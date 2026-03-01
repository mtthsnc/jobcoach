# Next Action

## Active Milestone

`M8` (Operational Hardening)

## Active Task

- Task ID: `M8-001`
- Task: Enforce bearer-auth guardrails on `/v1` endpoints with deterministic unauthorized responses and local-dev bypass control.
- Why now: `M8-PLAN-001` is complete, and auth enforcement is the first dependency for downstream M8 observability and async orchestration hardening tasks.

## Exact Next Steps

1. Implement auth guardrails in the gateway:
   - require bearer token validation for `/v1` endpoints,
   - preserve `/health` unauthenticated behavior,
   - add explicit local-dev bypass env control for deterministic local test execution.
2. Align contracts/tests with auth semantics:
   - update OpenAPI/error schema usage if needed for unauthorized responses,
   - add/extend unit + contract tests for missing, malformed, and valid bearer token flows.
3. Run validation and record handoff:
   - execute targeted tests plus full gates (`make test`, `make validate-openapi`, migrate up/down, `make contract-test`),
   - append START/END execution evidence in `docs/work-log.md`,
   - move pointer to `M8-002` after acceptance criteria pass.

## Validation Required

- Confirm `M8-001` acceptance criteria:
  - Missing/malformed bearer tokens return deterministic contract-valid `401` envelopes.
  - Authorized requests preserve existing endpoint behavior.
  - Local-dev bypass control is explicit, deterministic, and covered by tests.
  - Validation evidence is captured in `docs/work-log.md`.

## Return Pointer

After `M8-001` is complete, execute `M8-002`.
