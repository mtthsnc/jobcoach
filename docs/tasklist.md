# Tasklist

This is the executable backlog. Update status in place.

Status legend: `TODO`, `IN_PROGRESS`, `BLOCKED`, `DONE`

## Current Priority Queue

| ID | Status | Priority | Milestone | Task | Depends On | Acceptance Criteria |
|---|---|---|---|---|---|---|
| MONO-A | DONE | P0 | Monorepo Transition | Phase A preparation: freeze artifacts, create destination directories, and document old->new path mapping | None | Freeze snapshot + mapping table documented; destination directories exist; required validations pass with no behavior change |
| MONO-B | DONE | P0 | Monorepo Transition | Phase B relocation: move schemas/tooling to `schemas/` and `tools/scripts/` with compatibility shims | MONO-A | `make validate-openapi` and `make contract-test` pass after relocation |
| MONO-C | DONE | P0 | Monorepo Transition | Phase C extraction: move shared modules into `packages/` and update imports | MONO-B | Unit tests and contract tests pass |
| MONO-D | DONE | P1 | Monorepo Transition | Phase D cleanup: remove compatibility shims and sweep stale paths | MONO-C | All make targets pass and docs reflect final structure |
| M0-001 | DONE | P0 | M0 | Create repository skeleton (`apps/`, `services/`, `infra/`, `docs/`) | None | Directory structure committed and documented |
| M0-002 | DONE | P0 | M0 | Add OpenAPI spec file into runtime/canonical schema location (`schemas/openapi/openapi-m0-m2.yaml`) | M0-001 | Spec lint passes |
| M0-003 | DONE | P0 | M0 | Implement JSON schema validation package for core entities | M0-001 | Validation tests pass for valid and invalid fixtures |
| M0-004 | DONE | P0 | M0 | Add SQL migrations 001-004 and migration runner | M0-001 | Fresh DB migrate up/down works |
| M0-005 | DONE | P0 | M0 | Implement event outbox publisher interface | M0-004 | Events persisted and publish worker can dequeue |
| M0-006 | DONE | P0 | M0 | Set up CI checks (lint, tests, schema, migration checks) | M0-002,M0-003,M0-004 | CI workflow configured and local equivalent pipeline passes |
| M1-001 | DONE | P0 | M1 | Implement `POST /job-ingestions` and `GET /job-ingestions/{id}` | M0-002,M0-004 | Endpoints pass contract tests |
| M1-002 | DONE | P0 | M1 | Build job extraction worker (fetch, clean, segment) | M1-001 | Produces parsed sections on benchmark corpus |
| M1-003 | DONE | P0 | M1 | Add taxonomy normalization service stub + mappings | M0-003 | Terms map to canonical IDs |
| M1-004 | DONE | P0 | M1 | Persist `JobSpec` + evidence spans + confidence | M1-002,M1-003 | Schema-valid `JobSpec` persisted |
| M1-005 | DONE | P1 | M1 | Implement `PATCH /job-specs/{id}/review` with optimistic locking | M1-004 | Version conflict behavior covered by tests |
| M1-006 | DONE | P0 | M1 | Build extraction benchmark suite + threshold gates | M1-004,M0-006 | Threshold report emitted in CI |
| M2-001 | DONE | P0 | M2 | Implement `POST /candidate-ingestions` and status endpoint | M0-002,M0-004 | Endpoints pass contract tests |
| M2-002 | DONE | P0 | M2 | Implement CV parser into structured experiences | M2-001 | Parse output matches schema on fixture set |
| M2-003 | DONE | P0 | M2 | Implement storybank generator with quality scoring | M2-002,M1-003 | Stories include competencies and evidence score |
| M2-004 | DONE | P1 | M2 | Implement candidate profile/story retrieval endpoints | M2-002,M2-003 | Pagination and filters verified |
| M2-005 | DONE | P0 | M2 | Build candidate parse benchmark + threshold gates | M2-002,M2-003 | CI enforces parse quality thresholds |
| M3-PLAN-001 | DONE | P0 | M3 | Define executable M3 backlog with dependencies and acceptance criteria | M2-005 | M3 task graph is committed and NEXT pointer targets first executable M3 task |
| M3-001 | DONE | P0 | M3 | Extend interview session contracts + storage (`POST /interview-sessions`, `GET /interview-sessions/{id}`, `POST /interview-sessions/{id}/responses`) | M3-PLAN-001 | OpenAPI + schema fixtures + SQL migration for session lifecycle pass contract and migration checks |
| M3-002 | DONE | P0 | M3 | Build deterministic question planner from `JobSpec` + `CandidateProfile` competency targets | M3-001 | Planner emits coverage-balanced opening question set with deterministic ordering and confidence metadata |
| M3-003 | DONE | P0 | M3 | Implement adaptive follow-up selector using prior turn score + competency gaps | M3-002 | Follow-ups avoid repetition, attach rationale, and respect difficulty bounds in tests |
| M3-004 | DONE | P0 | M3 | Persist interview turns/scores and return schema-valid `InterviewSession` snapshots | M3-001,M3-002,M3-003 | End-to-end create/respond/get flow persists versioned session state and validates against core schema |
| M3-005 | DONE | P1 | M3 | Add interview orchestration API handlers with idempotent response ingestion semantics | M3-004 | Contract tests cover happy path, conflict, validation errors, and not-found behavior |
| M3-006 | DONE | P0 | M3 | Build interview relevance benchmark + threshold gates for CI/local | M3-004,M0-006 | Benchmark report emitted and CI fails on relevance/coverage threshold regressions |
| M3-007 | DONE | P1 | M3 | Add reviewer override path for low-confidence adaptive decisions | M3-005 | Override actions are auditable and regression-tested with optimistic locking |
| M4-PLAN-001 | DONE | P0 | M4 | Define executable M4 backlog with dependencies and acceptance criteria | M3-007 | M4 task graph committed and NEXT pointer targets first executable M4 task |
| M4-001 | DONE | P0 | M4 | Add `FeedbackReport` orchestration contract endpoints (`POST /feedback-reports`, `GET /feedback-reports/{id}`) | M4-PLAN-001 | OpenAPI + contract tests validate create/get flows and error semantics |
| M4-002 | DONE | P0 | M4 | Build deterministic session scoring aggregator across turn-level evidence and competency trends | M4-001 | Aggregated competency scores + overall score are deterministic and regression-tested |
| M4-003 | DONE | P0 | M4 | Generate root-cause gap analysis from low-performing competencies and response quality signals | M4-002 | Gap severity/root-cause outputs are schema-valid and consistent across fixed fixtures |
| M4-004 | DONE | P1 | M4 | Implement actionable rewrite suggestions and 30-day action-plan generation | M4-003 | Feedback reports include rewrites + action plan entries with bounded quality heuristics |
| M4-005 | DONE | P1 | M4 | Persist/retrieve feedback reports with idempotent generation semantics and optimistic versioning | M4-001,M4-002,M4-003,M4-004 | Storage layer supports idempotent report creation, replay, and conflict handling |
| M4-006 | DONE | P0 | M4 | Add feedback quality benchmark + threshold gates for CI/local | M4-005,M0-006 | Benchmark report emitted and CI fails on quality/coverage regressions |
| M5-PLAN-001 | DONE | P0 | M5 | Define executable M5 backlog with dependencies and acceptance criteria | M4-006 | M5 task graph committed and NEXT pointer targets first executable M5 task |
| M5-001 | DONE | P0 | M5 | Add `TrajectoryPlan` orchestration contract endpoints (`POST /trajectory-plans`, `GET /trajectory-plans/{id}`) + storage migration | M5-PLAN-001 | OpenAPI + schema fixtures + SQL migration for trajectory plan persistence pass contract and migration checks |
| M5-002 | DONE | P0 | M5 | Build deterministic longitudinal progress aggregator from interview sessions and feedback report history | M5-001 | Baseline/current/delta trend metrics are deterministic and regression-tested on fixed histories |
| M5-003 | DONE | P0 | M5 | Implement trajectory milestone + weekly-plan generator from trend metrics and target-role competency gaps | M5-002 | Generated `TrajectoryPlan` milestones/weekly plan are schema-valid, date-ordered, and evidence-linked |
| M5-004 | DONE | P1 | M5 | Persist/retrieve trajectory plans with idempotent generation semantics and optimistic version checks | M5-001,M5-003 | Storage supports idempotent replay, regeneration progression, and expected-version conflict behavior |
| M5-005 | DONE | P1 | M5 | Add candidate progress dashboard endpoint with competency trend cards and readiness signals | M5-002,M5-004 | Dashboard returns stable trend math and surfaces top-improving/top-risk competencies |
| M5-006 | DONE | P0 | M5 | Add trajectory quality benchmark + threshold gates for CI/local | M5-005,M0-006 | Benchmark report emitted and CI fails on trend-metric/trajectory-quality regressions |
| M6-PLAN-001 | DONE | P0 | M6 | Define executable M6 backlog with dependencies and acceptance criteria | M5-006 | M6 task graph is committed and NEXT pointer targets first executable M6 task |
| M6-001 | DONE | P0 | M6 | Add `NegotiationPlan` orchestration contract endpoints (`POST /negotiation-plans`, `GET /negotiation-plans/{id}`) + storage migration | M6-PLAN-001 | OpenAPI + schema fixtures + SQL migration for negotiation plan persistence pass contract and migration checks |
| M6-002 | DONE | P0 | M6 | Build deterministic negotiation-context aggregator from offer inputs + interview/feedback/trajectory history | M6-001 | Aggregated compensation targets, leverage factors, and risk signals are deterministic and fixture-tested |
| M6-003 | DONE | P0 | M6 | Implement negotiation strategy generator (anchor band, concession ladder, objection playbook) from context signals | M6-002 | Generated negotiation strategies are schema-valid, evidence-linked, and deterministic on fixed fixtures |
| M6-004 | DONE | P1 | M6 | Implement post-interview follow-up planner (thank-you draft, recruiter cadence, outcome branches) | M6-003 | Follow-up plans include date-bounded actions, template-safe drafts, and deterministic branch selection |
| M6-005 | DONE | P1 | M6 | Persist/retrieve negotiation plans with idempotent regeneration + optimistic version checks | M6-001,M6-003,M6-004 | Storage supports replay/conflict/version progression and returns schema-valid versioned negotiation plans |
| M6-006 | DONE | P0 | M6 | Add negotiation/follow-up quality benchmark + threshold gates for CI/local | M6-005,M0-006 | Benchmark report emitted and CI fails on negotiation-strategy/follow-up-quality regressions |
| M6-CLOSE-001 | DONE | P1 | M6 | Run final M6 stabilization sweep + release notes and close milestone | M6-006 | Full validation suite passes and M6 closeout notes are recorded with next-milestone handoff pointer |
| M7-PLAN-001 | DONE | P0 | M7 | Define executable M7 backlog with dependencies and acceptance criteria | M6-CLOSE-001 | M7 task graph is committed and NEXT pointer targets first executable M7 task |
| M7-001 | DONE | P0 | M7 | Implement `POST /taxonomy/normalize` API handler with deterministic normalization outputs and mapping persistence semantics | M7-PLAN-001 | Taxonomy normalize endpoint returns schema-valid deterministic term mappings and contract tests pass |
| M7-002 | DONE | P0 | M7 | Expand eval-run orchestration contracts/storage to support benchmark suite catalog and idempotent run requests | M7-PLAN-001 | OpenAPI + migration + repository semantics support versioned suite catalog and idempotent eval-run creation |
| M7-003 | DONE | P0 | M7 | Implement `POST /evals/run` orchestration flow (queued->running->terminal state transitions + metrics capture) | M7-002 | Eval run create returns `202 queued`, persists run state transitions, and deterministic executor unit tests pass |
| M7-004 | DONE | P0 | M7 | Implement `GET /evals/{eval_run_id}` retrieval endpoint with schema-valid status/metrics/error payloads | M7-003 | Eval run GET contract tests cover queued/running/succeeded/failed and not-found behaviors |
| M7-005 | TODO | P1 | M7 | Emit outbox lifecycle events for eval runs (queued/succeeded/failed) with retry-safe publication semantics | M7-003,M0-005 | Eval lifecycle events persist with deterministic payloads and retry/publish tests pass |
| M7-006 | TODO | P0 | M7 | Add eval-orchestration quality benchmark + CI/local threshold gate | M7-004,M7-005,M0-006 | Benchmark report emitted in CI/local and fails on status-transition/idempotency/metrics regressions |
| M7-CLOSE-001 | TODO | P1 | M7 | Run final M7 stabilization sweep + release notes and close milestone | M7-006 | Full validation suite passes and M7 closeout notes are recorded with next-milestone handoff pointer |
| M8-PLAN-001 | TODO | P0 | M8 | Define executable M8 backlog with dependencies and acceptance criteria | M7-CLOSE-001 | M8 task graph is committed and NEXT pointer targets first executable M8 task |

## NEXT

- `NEXT-1`: Execute `M7-005` (eval-run lifecycle outbox events).
- `NEXT-2`: Execute `M7-006` (eval-orchestration quality benchmark + threshold gate).

## Backlog (Future Milestones)

- M4: Scoring and feedback pipeline.
- M5: Progress tracking and trajectory planner.
- M6: Negotiation and post-interview assistant.
- M7: Taxonomy normalization and evaluation-ops orchestration.

## Update Rules

- Only one `IN_PROGRESS` task per active session.
- If blocked, add blocker details to `docs/work-log.md`.
- Do not move to `DONE` without explicit acceptance evidence.
