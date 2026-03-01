# API Surface

Runtime base path: `/v1`

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
