# Persistence, Idempotency, and Versioning

SQLite migrations create storage for:

- ingestion records (`job_ingestions`, `candidate_ingestions`)
- normalized artifacts (`job_specs`, `candidate_profiles`, `candidate_storybank`)
- interview runtime state (`interview_sessions`, `interview_session_responses`)
- coaching outputs (`feedback_reports`, `trajectory_plans`)
- taxonomy/eval/outbox support (`taxonomy_mappings`, `eval_runs`, `outbox_events`)

## Operational Semantics

- Mutation endpoints require `Idempotency-Key` where configured.
- Job spec review patch uses optimistic version checks.
- Feedback report creation supports conflict checks with expected/current versions.
- Trajectory plan creation includes idempotency conflict handling.

## Notes

- Canonical API contract: `schemas/openapi/openapi.yaml`
- Canonical entity schemas: `schemas/jsonschema/core-schemas.json`
- Migration files: `infra/migrations/*.sql`
