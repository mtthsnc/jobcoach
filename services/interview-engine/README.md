# services/interview-engine

## Purpose

Deterministic interview question planning and adaptive follow-up selection.

## Modules

- `planner.py`: ranks competencies from `JobSpec` and candidate evidence, then emits opening questions.
- `followup.py`: selects next follow-up competency/difficulty from session responses and score gaps.

## Inputs

- `JobSpec` competency weights.
- Candidate profile skills evidence.
- Interview session questions/scores/last response metadata.

## Outputs

- Planned opening question list with deterministic metadata.
- Follow-up selection decision (`competency`, `reason`, `difficulty`, `confidence`).

## Run and Validate

- `make test`
- `make benchmark-interview-relevance`
- `make contract-test`

## Dependencies

- Contract schema expectations from `schemas/jsonschema/core-schemas.json`.
- Consumed by API orchestration in `apps/api-gateway`.

## Ownership and Status

- Owner: TBD
- Status: Active
