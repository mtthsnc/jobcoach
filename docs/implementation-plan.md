# Implementation Plan

## 1. Engineering Principles

- Build from contracts outward.
- Prefer deterministic extraction over free-form generation.
- Enforce idempotent, observable workflows.
- Keep each phase shippable and testable.

## 2. Build Order

1. Contracts and data model (`M0`).
2. Job ingestion and extraction pipeline (`M1`).
3. Candidate parsing and storybank generation (`M2`).
4. Interview simulation engine (`M3`).
5. Feedback and root-cause analytics (`M4`).
6. Progress and trajectory intelligence (`M5`).
7. Negotiation and follow-up support (`M6`).
8. Taxonomy normalization and evaluation-ops orchestration (`M7`).
9. Operational hardening, security guardrails, and async orchestration reliability (`M8`).

## 3. Milestone Plan

## M0: Foundations

### Deliverables

- OpenAPI starter contract.
- JSON schemas for core entities.
- SQL migrations for foundational tables.
- Event contract definitions.
- Eval harness skeleton.

### Acceptance criteria

- Schema validation active in CI.
- API stubs compile and pass contract tests.
- DB migrations apply/rollback cleanly.

## M1: Job Ingestion + Structuring

### Deliverables

- `POST/GET /job-ingestions`.
- Extraction worker (fetch, clean, segment, normalize).
- `GET /job-specs/{id}` and review patch endpoint.
- Confidence + evidence spans in persisted outputs.

### Acceptance criteria

- >= 90% benchmark jobs become valid `JobSpec`.
- Section detection and skill mapping are above threshold.
- Low-confidence fields are flagged for review.

## M2: Candidate Profile + Storybank

### Deliverables

- `POST/GET /candidate-ingestions`.
- CV parser into timeline, skills, and achievements.
- Storybank generation with quality scoring.
- Profile/story retrieval endpoints.

### Acceptance criteria

- >= 85% candidate inputs parse to valid profile.
- Storybank quality flags available for weak evidence.
- Story coverage against target competencies reported.

## M3: Adaptive Interview Engine

### Deliverables

- Interview session API lifecycle: create session, append candidate response, retrieve session state.
- Deterministic question planner seeded by `JobSpec` competency weights and candidate storybank coverage.
- Adaptive follow-up selector that responds to prior turn score, competency risk, and difficulty progression.
- Persisted, schema-valid `InterviewSession` snapshots with turn history, per-question scores, and overall score.
- Quality benchmark suite for interview relevance/coverage with threshold gating in CI.

### Acceptance criteria

- Interview session create/respond/get contract tests pass against OpenAPI and core schema constraints.
- Adaptive planner demonstrates competency coverage and non-repetition behavior on fixture corpus.
- >= 95% generated session snapshots validate as `InterviewSession`.
- Benchmark relevance score meets or exceeds M3 gate threshold (>= 0.80).
- Low-confidence adaptive outputs are explicitly flagged for reviewer override.

## M7: Taxonomy + Evaluation Operations

### Deliverables

- `POST /taxonomy/normalize` gateway wiring with deterministic normalization outputs.
- `POST /evals/run` orchestration flow with persisted run-state transitions.
- `GET /evals/{eval_run_id}` retrieval endpoint for queued/running/terminal eval states.
- Eval lifecycle outbox events for queued/succeeded/failed transitions.
- Eval-orchestration benchmark and threshold gate integrated into local/CI validation.

### Acceptance criteria

- Taxonomy normalize endpoint passes schema/contract tests and deterministic fixture checks.
- Eval run create/get flows pass contract tests for queued/running/succeeded/failed/not-found semantics.
- Eval lifecycle event payloads persist and pass retry/publish behavior tests.
- Eval-orchestration benchmark passes configured threshold gates in `make test` and CI.

## M8: Operational Hardening + Reliability

### Deliverables

- Bearer-auth enforcement for `/v1` endpoints with deterministic unauthorized error semantics and explicit local-dev bypass controls.
- Structured request logs with request/correlation IDs, route/status/latency fields, and sensitive-field redaction for candidate/job free-text payloads.
- Worker-driven outbox relay with bounded retry/backoff and dead-letter behavior for repeatedly failing publishes.
- Async eval orchestration path where `POST /evals/run` enqueues work and worker execution drives `queued -> running -> terminal` state transitions.
- Runtime health/readiness probes and latency benchmark gate for read endpoints.

### Acceptance criteria

- Unauthorized or malformed auth requests return contract-valid `401` envelopes and authorized flows retain existing contract behavior.
- Structured logs include deterministic request metadata and exclude raw sensitive payload text according to redaction policy tests.
- Outbox relay publishes ready events with retry-safe dedup semantics, bounded retries, and deterministic dead-letter transitions under failure.
- Eval runs transition through persisted async lifecycle states via worker execution, with create/get contract and orchestration benchmarks passing.
- Runtime readiness checks and read-path latency benchmark (`p95 <= 400ms`) are enforced by local/CI validation commands.

## 4. Suggested Sprint Breakdown

- Sprint 1: M0 contracts + migrations + test scaffolding.
- Sprint 2: M1 ingestion API + extraction worker v1.
- Sprint 3: M1 normalization + quality checks + review path.
- Sprint 4: M2 parser + profile persistence.
- Sprint 5: M2 storybank generator + quality/eval hardening.
- Sprint 6: M3 contracts + session persistence + deterministic planner base.
- Sprint 7: M3 adaptive follow-up logic + orchestration endpoint hardening.
- Sprint 8: M3 benchmark thresholds + reviewer override path.

## 5. Service Boundaries (M0-M3)

- `api-gateway`: auth, validation, idempotency.
- `orchestrator`: workflow state transitions.
- `job-extraction-service`: job content parsing and normalization.
- `candidate-profile-service`: CV parsing and storybank generation.
- `taxonomy-service`: canonical term mapping.
- `quality-eval-service`: schema and benchmark validation.
- `interview-engine-service`: question planning, follow-up adaptation, and session scoring state transitions.

## 6. Non-Functional Requirements

- API p95 under 400ms for read endpoints.
- Ingestion retry policy with bounded backoff.
- Structured logs with correlation IDs.
- Encryption and retention policy for sensitive artifacts.

## 7. Test Strategy

- Contract tests for all API shapes.
- Migration tests for apply + rollback.
- Benchmark suites for extraction/parsing quality.
- Interview simulation tests for turn sequencing, adaptation rules, and score progression.
- Workflow tests for retries and failure modes.

## 8. Release Strategy

- Feature flags per milestone capability.
- Blue/green or canary for major pipeline upgrades.
- No phase marked complete without acceptance gate evidence.
