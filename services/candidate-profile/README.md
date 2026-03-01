# services/candidate-profile

## Purpose

Deterministic candidate profile parsing and STAR storybank generation for ingestion flows.

## Modules

- `parser.py`: builds schema-aligned `CandidateProfile` payloads from CV text/reference input.
- `storybank.py`: generates deterministic STAR stories with competency tags and evidence quality scoring.

## Inputs

- Candidate ingestion payload fields (`ingestion_id`, `candidate_id`, `cv_text` or `cv_document_ref`, `target_roles`, `story_notes`).
- Parsed experience records used for story generation.

## Outputs

- `CandidateProfile` payload shape consumed by API handlers and persistence logic.
- Storybank entries associated to a candidate profile.

## Run and Validate

- `make test`
- `make benchmark-candidate-parse`
- `make contract-test`

## Dependencies

- Canonical schema definitions in `schemas/jsonschema/core-schemas.json`.
- Consumed by `apps/api-gateway` ingestion and retrieval endpoints.

## Ownership and Status

- Owner: TBD
- Status: Active
