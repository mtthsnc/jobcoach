# services/progress-tracking

## Purpose

Deterministic longitudinal progress aggregation across interview and feedback history.

## Modules

- `aggregator.py`: merges session/report history into baseline/current/delta summaries and competency trends.

## Inputs

- Interview session snapshots (questions, scores, timestamps).
- Feedback report snapshots (competency scores, overall scores, timestamps).

## Outputs

- Progress summary payloads including:
  - history counts
  - baseline/current/delta scores
  - competency trends
  - top improving and top risk competencies

## Run and Validate

- `make test`
- `make benchmark-trajectory-quality`
- `make contract-test`

## Dependencies

- Consumed by trajectory planning and progress dashboard API handlers.
- Contract validation via `schemas/jsonschema/core-schemas.json`.

## Ownership and Status

- Owner: TBD
- Status: Active
