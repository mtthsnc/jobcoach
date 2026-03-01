# services/job-extraction

## Purpose

Deterministic job source extraction and section segmentation for ingestion flows.

## Modules

- `worker.py`: fetches source content (`text`, `url`, `document_ref`), cleans text, derives role title, and segments canonical sections.

## Inputs

- Job ingestion payload fields (`source_type`, `source_value`).

## Outputs

- `ExtractedJobDocument` payload with `role_title`, `cleaned_text`, and normalized section entries.

## Run and Validate

- `make test`
- `make benchmark-extraction`
- `make contract-test`

## Dependencies

- Optional URL fetching via Python stdlib `urllib`.
- Downstream taxonomy normalization (`services/taxonomy`) and `JobSpec` persistence in API handlers.

## Ownership and Status

- Owner: TBD
- Status: Active
