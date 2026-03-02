# API Surface

Runtime base path: `/v1`

Auth guardrails:
- `/v1/*` endpoints require `Authorization: Bearer <token>`.
- `/health` remains unauthenticated for liveness probing.
- `/readiness` remains unauthenticated for runtime dependency readiness probing (process + DB).
- Local-dev bypass is controlled explicitly via `JOBCOACH_AUTH_BYPASS=true`.

Request observability guardrails:
- Gateway emits structured JSON request logs with `method`, `path`, `route`, `status`, `request_id`, `latency_ms`, and `request_body_bytes`.
- `request_id` propagates from inbound `x-request-id` when supplied and is linked to response envelope `meta.request_id`.
- High-risk free-text fields are redacted in log metadata (`cv_text`, `story_notes`, and free-text `source_value` payloads).

Outbox relay guardrails:
- Relay worker publishes pending outbox rows deterministically (`available_at` then `created_at` order).
- Publish failures increment `publish_attempts`, persist bounded `last_error`, and schedule deterministic retry backoff.
- Retry-exhausted events transition to terminal dead-letter state (`status=failed`) with `dead_lettered_at` metadata.

Eval orchestration guardrails:
- `POST /v1/evals/run` is enqueue-only and returns deterministic queued acknowledgements.
- Eval execution occurs in worker polls that deterministically claim queued runs (`created_at`, then `eval_run_id`).
- Worker transitions persist `queued -> running -> terminal` metadata and emit relay-compatible lifecycle outbox events (`eval_run.queued`, terminal event).

Runtime probe guardrails:
- `/health` returns deterministic liveness envelope (`status=ok`) and does not check dependencies.
- `/readiness` verifies core process + database dependency checks with deterministic envelopes.
- `/readiness` returns `200` when all checks pass and `503 service_unavailable` with structured failure details when any required check fails.

## Implemented Endpoints (API Gateway)

- `POST /job-ingestions`
- `GET /job-ingestions/{ingestion_id}`
- `GET /job-specs/{job_spec_id}`
- `PATCH /job-specs/{job_spec_id}/review`
- `POST /candidate-ingestions`
- `GET /candidate-ingestions/{ingestion_id}`
- `GET /candidates/{candidate_id}/profile`
- `GET /candidates/{candidate_id}/storybank`
- `POST /taxonomy/normalize`
- `POST /interview-sessions`
- `GET /interview-sessions/{session_id}`
- `POST /interview-sessions/{session_id}/responses`
- `POST /feedback-reports`
- `GET /feedback-reports/{feedback_report_id}`
- `POST /trajectory-plans`
- `GET /trajectory-plans/{trajectory_plan_id}`
- `POST /evals/run`
- `GET /evals/{eval_run_id}`

## Canonical Contract Artifacts

- OpenAPI: `schemas/openapi/openapi.yaml`
- JSON Schema: `schemas/jsonschema/core-schemas.json`

## Internal Outbox Lifecycle Events

- `eval_run.queued`
- `eval_run.succeeded`
- `eval_run.failed`
