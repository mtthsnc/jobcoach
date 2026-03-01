# services/trajectory-planning

## Purpose

Deterministic trajectory plan generation from candidate profile and longitudinal progress signals.

## Modules

- `generator.py`: computes role readiness, prioritized gap focus, milestone timeline, and weekly action plan.

## Inputs

- Candidate profile skill scores.
- Target role string.
- Progress summary output from `services/progress-tracking`.

## Outputs

- Trajectory planning payload with:
  - horizon
  - readiness score
  - milestones
  - weekly plan actions

## Run and Validate

- `make test`
- `make benchmark-trajectory-quality`
- `make contract-test`

## Dependencies

- Consumes progress summary semantics from `services/progress-tracking`.
- Contract validation via `schemas/jsonschema/core-schemas.json`.

## Ownership and Status

- Owner: TBD
- Status: Active
