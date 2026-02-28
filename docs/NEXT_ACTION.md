# Next Action

## Active Milestone

`Monorepo Transition` (Pre-roadmap structural stream)

## Active Task

- Task ID: `MONO-B`
- Task: Execute Monorepo Phase B (Schema/Tooling Relocation).
- Why now: Phase A preparation is complete; transition can proceed with controlled path moves and compatibility shims.

## Exact Next Steps

1. Read `docs/monorepo-fresh-context.md` and use it as execution authority for transition phases.
2. Use `docs/monorepo-phase-a-freeze.md` as the frozen mapping/checksum authority for planned moves.
3. Relocate schema assets to `schemas/openapi` and `schemas/jsonschema`.
4. Relocate reusable scripts to `tools/scripts`.
5. Add compatibility links/stubs for legacy paths and update references incrementally.
6. Keep behavior unchanged while completing Phase B.

## Validation Required

- Existing targets still pass after relocation:
  - `make test`
  - `make validate-openapi`
  - `make migrate-up`
  - `make migrate-down`
  - `make contract-test` (use escalated run in this environment if port binding is blocked).

## Return Pointer

After monorepo phases complete, set this file back to roadmap execution at `M1-002` unless superseded.
