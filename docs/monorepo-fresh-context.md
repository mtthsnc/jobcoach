# Monorepo Fresh Context Plan

Purpose: provide a single restart document for executing monorepo restructuring, then resuming the original delivery tasklist without losing momentum.

## 1. Why this exists

- We want a clean context-reset entrypoint before monorepo changes.
- We need to protect current M0/M1 progress while changing repository structure.
- After monorepo work, execution must return to the original roadmap/tasklist.

## 2. Current Baseline (as of 2026-02-28)

- M0 completed: contracts, migrations, validation harness, outbox interface, CI scaffold.
- M1-001 completed: `POST/GET /v1/job-ingestions` plus contract tests.
- Current roadmap pointer before monorepo work: `M1-002` in `docs/NEXT_ACTION.md`.

## 3. Monorepo Target Shape

```text
apps/
  api-gateway/
  coach-api/                 # future
services/
  job-extraction/
  orchestrator/
  candidate-profile/
  taxonomy/
  quality-eval/
packages/
  contracts/                 # generated/openapi/json-schema consumers
  db/                        # shared DB helpers and migration wrappers
  eventing/                  # outbox + event utilities
  observability/             # logging/trace helpers
schemas/
  openapi/
  jsonschema/
infra/
  migrations/
tools/
  scripts/
tests/
docs/
```

## 4. Execution Rules

- Contracts-first: schema artifacts are source of truth.
- No behavior rewrite during structural moves.
- One move wave at a time: move, relink imports, run tests.
- Keep `make test`, `make contract-test`, `make validate-openapi`, `make migrate-up/down` green after each wave.
- If a move breaks validation, stop and fix before continuing.

## 5. Monorepo Transition Phases

### Phase A: Preparation

1. Freeze current contracts and migrations.
2. Create destination directories (`packages/`, `schemas/`, `tools/`).
3. Add mapping table: old path -> new path.

Exit criteria:
- Move plan reviewed in docs.
- No runtime behavior change yet.

Phase A execution record:
- See `docs/monorepo-phase-a-freeze.md` for the frozen artifact checksums, reference inventory, and old->new path mapping table captured on `2026-02-28`.

### Phase B: Schema/Tooling Relocation

1. Move OpenAPI and JSON schemas to `schemas/`.
2. Move reusable scripts to `tools/scripts/`.
3. Add compatibility links/stubs from old paths.

Exit criteria:
- `make validate-openapi` passes.
- Contract tests still pass.

### Phase C: Shared Package Extraction

1. Move reusable modules into `packages/` (`contracts`, `db`, `eventing`).
2. Update imports in `apps/` and `services/`.
3. Keep tests unchanged where possible.

Exit criteria:
- Unit tests pass.
- Contract tests pass.

### Phase D: Cleanup and Hardening

1. Remove temporary compatibility shims.
2. Update docs (`README`, service ownership, runbook).
3. Confirm no stale paths remain (`rg` sweep).

Exit criteria:
- All make targets pass.
- Docs reflect final structure.

## 6. Resume Protocol After Context Reset

When a new session starts:

1. Read `docs/README.md`.
2. Read this file: `docs/monorepo-fresh-context.md`.
3. Read `docs/NEXT_ACTION.md`.
4. Execute the active monorepo phase task.
5. Update `docs/work-log.md` and `docs/NEXT_ACTION.md` at end.

Use template prompt: `docs/templates/resume-prompt.md`.

## 7. Return to Original Tasklist

After monorepo transition is complete:

1. Set `docs/NEXT_ACTION.md` back to product roadmap execution (`M1-002` unless superseded).
2. Continue from `docs/tasklist.md` in normal order.
3. Do not create a separate roadmap; monorepo work is a temporary structural stream.

## 8. Validation Checklist (must pass before returning)

- `make lint`
- `make test`
- `make validate-openapi`
- `make migrate-up`
- `make migrate-down`
- `make contract-test`

If `make contract-test` requires port binding, run with escalated permissions in this environment.
