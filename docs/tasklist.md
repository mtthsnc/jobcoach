# Tasklist

This is the executable backlog. Update status in place.

Status legend: `TODO`, `IN_PROGRESS`, `BLOCKED`, `DONE`

## Current Priority Queue

| ID | Status | Priority | Milestone | Task | Depends On | Acceptance Criteria |
|---|---|---|---|---|---|---|
| MONO-A | DONE | P0 | Monorepo Transition | Phase A preparation: freeze artifacts, create destination directories, and document old->new path mapping | None | Freeze snapshot + mapping table documented; destination directories exist; required validations pass with no behavior change |
| MONO-B | TODO | P0 | Monorepo Transition | Phase B relocation: move schemas/tooling to `schemas/` and `tools/scripts/` with compatibility shims | MONO-A | `make validate-openapi` and `make contract-test` pass after relocation |
| MONO-C | TODO | P0 | Monorepo Transition | Phase C extraction: move shared modules into `packages/` and update imports | MONO-B | Unit tests and contract tests pass |
| MONO-D | TODO | P1 | Monorepo Transition | Phase D cleanup: remove compatibility shims and sweep stale paths | MONO-C | All make targets pass and docs reflect final structure |
| M0-001 | DONE | P0 | M0 | Create repository skeleton (`apps/`, `services/`, `infra/`, `docs/`) | None | Directory structure committed and documented |
| M0-002 | DONE | P0 | M0 | Add OpenAPI spec file from `docs/artifacts/openapi-m0-m2.yaml` into runtime location | M0-001 | Spec lint passes |
| M0-003 | DONE | P0 | M0 | Implement JSON schema validation package for core entities | M0-001 | Validation tests pass for valid and invalid fixtures |
| M0-004 | DONE | P0 | M0 | Add SQL migrations 001-004 and migration runner | M0-001 | Fresh DB migrate up/down works |
| M0-005 | DONE | P0 | M0 | Implement event outbox publisher interface | M0-004 | Events persisted and publish worker can dequeue |
| M0-006 | DONE | P0 | M0 | Set up CI checks (lint, tests, schema, migration checks) | M0-002,M0-003,M0-004 | CI workflow configured and local equivalent pipeline passes |
| M1-001 | DONE | P0 | M1 | Implement `POST /job-ingestions` and `GET /job-ingestions/{id}` | M0-002,M0-004 | Endpoints pass contract tests |
| M1-002 | TODO | P0 | M1 | Build job extraction worker (fetch, clean, segment) | M1-001 | Produces parsed sections on benchmark corpus |
| M1-003 | TODO | P0 | M1 | Add taxonomy normalization service stub + mappings | M0-003 | Terms map to canonical IDs |
| M1-004 | TODO | P0 | M1 | Persist `JobSpec` + evidence spans + confidence | M1-002,M1-003 | Schema-valid `JobSpec` persisted |
| M1-005 | TODO | P1 | M1 | Implement `PATCH /job-specs/{id}/review` with optimistic locking | M1-004 | Version conflict behavior covered by tests |
| M1-006 | TODO | P0 | M1 | Build extraction benchmark suite + threshold gates | M1-004,M0-006 | Threshold report emitted in CI |
| M2-001 | TODO | P0 | M2 | Implement `POST /candidate-ingestions` and status endpoint | M0-002,M0-004 | Endpoints pass contract tests |
| M2-002 | TODO | P0 | M2 | Implement CV parser into structured experiences | M2-001 | Parse output matches schema on fixture set |
| M2-003 | TODO | P0 | M2 | Implement storybank generator with quality scoring | M2-002,M1-003 | Stories include competencies and evidence score |
| M2-004 | TODO | P1 | M2 | Implement candidate profile/story retrieval endpoints | M2-002,M2-003 | Pagination and filters verified |
| M2-005 | TODO | P0 | M2 | Build candidate parse benchmark + threshold gates | M2-002,M2-003 | CI enforces parse quality thresholds |

## NEXT

- `NEXT-1`: Execute `MONO-B` by relocating schema/tooling assets to `schemas/` and `tools/scripts/` with compatibility shims and no behavior change.
- `NEXT-2`: After monorepo phases are complete, return to `M1-002` and resume product roadmap execution.

## Backlog (Future Milestones)

- M3: Adaptive interview engine.
- M4: Scoring and feedback pipeline.
- M5: Progress tracking and trajectory planner.
- M6: Negotiation and post-interview assistant.

## Update Rules

- Only one `IN_PROGRESS` task per active session.
- If blocked, add blocker details to `docs/work-log.md`.
- Do not move to `DONE` without explicit acceptance evidence.
