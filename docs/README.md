# JobCoach Documentation Hub

This folder is the persistent operating system for building the AI-powered career and interview coaching platform.

If chat context runs out, a new session should resume by following this exact order:

1. Read `docs/session-continuity.md`.
2. Read `docs/masterplan.md` for product and architecture intent.
3. Read `docs/implementation-plan.md` for current build sequence.
4. Read `docs/tasklist.md` and continue the top `NEXT` item.
5. Read `docs/NEXT_ACTION.md` for the latest handoff pointer.
6. Append a new entry in `docs/work-log.md` before and after doing work.

## File Map

- `docs/api-surface.md`: Runtime API endpoint inventory and contract implementation status.
- `docs/quality-gates.md`: Benchmark thresholds, test strategy, and validation command sequence.
- `docs/persistence-versioning.md`: Storage model and idempotency/versioning semantics.
- `docs/masterplan.md`: End-state vision, scope, architecture, and milestones.
- `docs/implementation-plan.md`: Phase-by-phase engineering plan with acceptance gates.
- `docs/monorepo-fresh-context.md`: Restart playbook for monorepo transition, then return to roadmap tasks.
- `docs/monorepo-phase-a-freeze.md`: Phase A freeze snapshot (checksums, references, and old->new path mapping).
- `docs/m6-release-notes.md`: M6 closeout summary (scope delivered, validations, gates, and environment caveats).
- `docs/m7-release-notes.md`: M7 closeout summary (scope delivered, validations, gates, and environment caveats).
- `docs/tasklist.md`: Executable backlog with priorities, dependencies, and status.
- `docs/session-continuity.md`: How to resume/close sessions safely.
- `docs/NEXT_ACTION.md`: Single canonical "what to do next" pointer.
- `docs/work-log.md`: Chronological execution log across sessions.
- `docs/decision-log.md`: ADR-style decision records.
- `docs/risk-register.md`: Live risk tracking and mitigation.
- `docs/templates/handoff-template.md`: Required format for end-of-session handoff.
- `docs/templates/task-template.md`: Template for adding new backlog tasks.
- `docs/templates/resume-prompt.md`: Copy-paste prompt for starting a fresh session.
- `schemas/openapi/openapi-m0-m2.yaml`: Canonical API contract artifact.
- `schemas/openapi/openapi.yaml`: Canonical runtime OpenAPI pointer.
- `schemas/jsonschema/core-schemas.json`: Canonical core JSON schemas artifact.

## Update Rules

- Keep `docs/NEXT_ACTION.md` up to date at all times.
- Never mark a task complete unless its acceptance criteria are verified.
- Every session must write a start and end note in `docs/work-log.md`.
- Architectural changes must be recorded in `docs/decision-log.md`.
- If priorities change, update both `docs/masterplan.md` and `docs/tasklist.md`.
