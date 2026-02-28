# JobCoach

JobCoach is an API-first, deterministic AI coaching backend that helps candidates prepare for specific roles instead of practicing generic interview content.

It ingests a job posting and candidate profile, generates role-targeted mock interview sessions, scores performance, produces actionable feedback, and tracks readiness trends over time.

## Why This Exists

Most candidates prepare too broadly. They struggle to translate their own experience into the hiring signals for a specific target role.

JobCoach is designed to solve that by making preparation:

- Role-grounded: starts from a real job description.
- Candidate-grounded: starts from real CV experience and story notes.
- Measurable: tracks competency-level trend movement over sessions.
- Actionable: produces concrete gaps, rewrites, and preparation plans.

## What The System Does

End-to-end workflow:

1. Ingest a job source (`url`, `text`, `document_ref`) and build a normalized `JobSpec`.
2. Ingest candidate CV input and notes and build a `CandidateProfile` + STAR storybank.
3. Create interview sessions with deterministic opening questions and adaptive follow-ups.
4. Generate `FeedbackReport` outputs with top gaps, root causes, rewrites, and 30-day action plans.
5. Aggregate longitudinal trends and generate `TrajectoryPlan` readiness plans.

## Current Project Status

As of `2026-02-28`, milestones `M0` through `M4` are complete, `M5` is active, and `M6` (negotiation/post-interview modules) is planned.

Implemented in current backend:

- Job ingestion + extraction + taxonomy mapping + `JobSpec` persistence/review.
- Candidate ingestion + deterministic profile parsing + storybank generation/retrieval.
- Interview session lifecycle (create/respond/get) with adaptive follow-up logic.
- Feedback report lifecycle (create/get) with deterministic scoring and gap analysis.
- Progress-tracking aggregation and trajectory-plan endpoint/storage.

In progress:

- Trajectory generator integration/hardening for target-role gap-aware milestone generation (`M5-003`/`M5-004` stream).

Planned:

- Negotiation and post-interview support (`M6`).

## Architecture

High-level flow:

`Ingestion -> Extraction/Parsing -> Interview Engine -> Feedback -> Progress Tracking -> Trajectory Planning`

Key design principles:

- Contracts-first: OpenAPI + JSON Schema are source-of-truth.
- Deterministic behavior preferred over unconstrained generation.
- Evidence-linked outputs and confidence metadata.
- Idempotent mutation endpoints and optimistic version checks where relevant.

## Monorepo Layout

```text
apps/
  api-gateway/                 # WSGI API server and endpoint handlers
services/
  job-extraction/              # job text/html cleaning + section segmentation
  taxonomy/                    # term normalization
  candidate-profile/           # CV parser + storybank generator
  interview-engine/            # opening planner + follow-up selector
  progress-tracking/           # longitudinal trend aggregation
  trajectory-planning/         # deterministic trajectory generator module (active)
  quality-eval/                # schema validator + benchmark runners
  orchestrator/                # workflow scaffold
packages/
  db/                          # SQLite helpers
  eventing/                    # outbox/event utilities
  contracts/                   # contract artifact helpers
schemas/
  openapi/                     # API contracts (openapi.yaml -> openapi-m0-m2.yaml)
  jsonschema/                  # core entity schemas
infra/
  migrations/                  # SQLite migrations
tests/
  unit/                        # deterministic unit and benchmark tests
  contracts/                   # contract + API flow tests
docs/                          # roadmap, tasklist, continuity, decisions
```

## Core Data Contracts

Canonical entities:

- `JobSpec`
- `CandidateProfile`
- `InterviewSession`
- `FeedbackReport`
- `TrajectoryPlan`

Artifacts live in:

- `schemas/openapi/openapi.yaml`
- `schemas/jsonschema/core-schemas.json`

## API Surface

Runtime base path: `/v1`

### Implemented endpoints (API gateway)

- `POST /job-ingestions`
- `GET /job-ingestions/{ingestion_id}`
- `GET /job-specs/{job_spec_id}`
- `PATCH /job-specs/{job_spec_id}/review`
- `POST /candidate-ingestions`
- `GET /candidate-ingestions/{ingestion_id}`
- `GET /candidates/{candidate_id}/profile`
- `GET /candidates/{candidate_id}/storybank`
- `POST /interview-sessions`
- `GET /interview-sessions/{session_id}`
- `POST /interview-sessions/{session_id}/responses`
- `POST /feedback-reports`
- `GET /feedback-reports/{feedback_report_id}`
- `POST /trajectory-plans`
- `GET /trajectory-plans/{trajectory_plan_id}`

### Contract-defined, not fully wired in current gateway handlers

- `POST /taxonomy/normalize`
- `POST /evals/run`
- `GET /evals/{eval_run_id}`

## Local Quickstart

### Prerequisites

- Python `3.x` available as `python3`
- `make`

Current code paths are intentionally dependency-light and rely on Python standard library for the API, tests, and tooling.

### 1) Prepare database

```bash
make migrate-up
```

Default DB path is `.tmp/migrate-local.sqlite3` (overridable via `MIGRATE_DB_PATH`).

### 2) Start API

```bash
HOST=127.0.0.1 PORT=8000 JOBCOACH_DB_PATH=.tmp/migrate-local.sqlite3 python3 apps/api-gateway/serve.py
```

### 3) Smoke test core flow

Create job ingestion from text:

```bash
curl -sS -X POST http://127.0.0.1:8000/v1/job-ingestions \
  -H 'content-type: application/json' \
  -H 'Idempotency-Key: demo-job-1' \
  -d '{"source_type":"text","source_value":"Senior Backend Engineer\nResponsibilities:\n- Build reliable APIs\nRequirements:\n- Python\n- SQL"}'
```

Create candidate ingestion:

```bash
curl -sS -X POST http://127.0.0.1:8000/v1/candidate-ingestions \
  -H 'content-type: application/json' \
  -H 'Idempotency-Key: demo-candidate-1' \
  -d '{"candidate_id":"cand_demo_1","cv_text":"Maya Rivera\nSenior Engineer\nBackend Engineer at Acme (2021-01 to present)","story_notes":["Reduced API p95 by 45%"],"target_roles":["Senior Backend Engineer"]}'
```

Then continue with `GET` ingestion status endpoints to retrieve created entity IDs and call:

- `POST /v1/interview-sessions`
- `POST /v1/feedback-reports`
- `POST /v1/trajectory-plans`

## Development Commands

Show all available targets:

```bash
make help
```

Primary targets:

- `make test`: unit tests + all benchmark threshold gates
- `make validate-openapi`: OpenAPI structural validation
- `make contract-test`: migration smoke + contract tests (+ API contract flow tests)
- `make migrate-up`: apply migrations
- `make migrate-down`: up+down rollback verification
- `make benchmark-extraction`
- `make benchmark-candidate-parse`
- `make benchmark-interview-relevance`
- `make benchmark-feedback-quality`

## Quality Gates

Benchmark threshold defaults enforced in CI/local:

- Extraction benchmark:
  - `role_title_accuracy >= 0.90`
  - `section_coverage >= 0.90`
  - `skill_precision >= 0.80`
  - `skill_recall >= 0.80`
  - `jobspec_valid_rate >= 0.90`
- Candidate parse benchmark:
  - `candidate_profile_valid_rate >= 0.95`
  - `required_field_coverage >= 0.90`
  - `story_quality_p50 >= 0.70`
  - `story_quality_p10 >= 0.65`
- Interview relevance benchmark:
  - `overall_relevance >= 0.90`
  - plus coverage/alignment/non-repetition/difficulty bounds
- Feedback quality benchmark:
  - `overall_feedback_quality >= 0.90`
  - plus completeness/root-cause/evidence/rewrite/action-plan checks

## Persistence, Idempotency, and Versioning

SQLite migrations create storage for:

- ingestion records (`job_ingestions`, `candidate_ingestions`)
- normalized artifacts (`job_specs`, `candidate_profiles`, `candidate_storybank`)
- interview runtime state (`interview_sessions`, `interview_session_responses`)
- coaching outputs (`feedback_reports`, `trajectory_plans`)
- taxonomy/eval/outbox support (`taxonomy_mappings`, `eval_runs`, `outbox_events`)

Operational semantics:

- Mutation endpoints require `Idempotency-Key` where configured.
- Job spec review patch uses optimistic version checks.
- Feedback report creation supports conflict checks with expected/current versions.
- Trajectory plan creation includes idempotency conflict handling.

## Testing Strategy

- Unit tests validate deterministic service behavior.
- Contract tests validate schema artifacts and OpenAPI structure.
- API contract tests launch a local API process against a fresh SQLite schema.

Run full local gate sequence:

```bash
make test
make validate-openapi
make migrate-up
make migrate-down
make contract-test
```

## Documentation and Execution Runbook

Start here for roadmap/continuity:

- `docs/README.md`
- `docs/masterplan.md`
- `docs/implementation-plan.md`
- `docs/tasklist.md`
- `docs/NEXT_ACTION.md`
- `docs/work-log.md`

## Roadmap

- `M0`: Foundations (contracts, schema validation, migrations, outbox) ✅
- `M1`: Job ingestion and extraction ✅
- `M2`: Candidate parsing and storybank ✅
- `M3`: Adaptive interview orchestration ✅
- `M4`: Feedback and gap analytics ✅
- `M5`: Progress tracking and trajectory intelligence (active)
- `M6`: Negotiation and post-interview support (planned)

## Notes

- This repository currently prioritizes deterministic backend behavior and quality gates over production deployment scaffolding.
- Service READMEs in some directories are still scaffold placeholders while implementation lives in module code and tests.
