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

## 4. Suggested Sprint Breakdown

- Sprint 1: M0 contracts + migrations + test scaffolding.
- Sprint 2: M1 ingestion API + extraction worker v1.
- Sprint 3: M1 normalization + quality checks + review path.
- Sprint 4: M2 parser + profile persistence.
- Sprint 5: M2 storybank generator + quality/eval hardening.

## 5. Service Boundaries (M0-M2)

- `api-gateway`: auth, validation, idempotency.
- `orchestrator`: workflow state transitions.
- `job-extraction-service`: job content parsing and normalization.
- `candidate-profile-service`: CV parsing and storybank generation.
- `taxonomy-service`: canonical term mapping.
- `quality-eval-service`: schema and benchmark validation.

## 6. Non-Functional Requirements

- API p95 under 400ms for read endpoints.
- Ingestion retry policy with bounded backoff.
- Structured logs with correlation IDs.
- Encryption and retention policy for sensitive artifacts.

## 7. Test Strategy

- Contract tests for all API shapes.
- Migration tests for apply + rollback.
- Benchmark suites for extraction/parsing quality.
- Workflow tests for retries and failure modes.

## 8. Release Strategy

- Feature flags per milestone capability.
- Blue/green or canary for major pipeline upgrades.
- No phase marked complete without acceptance gate evidence.
