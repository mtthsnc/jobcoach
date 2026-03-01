# services/taxonomy

## Purpose

Deterministic normalization of extracted terms into canonical taxonomy identifiers.

## Modules

- `normalizer.py`: mapping-first term normalization and bridge helpers for job requirement terms.
- `mappings/skill_terms.json`: canonical alias-to-skill mapping source.

## Inputs

- Raw extracted requirement terms (required/preferred skill strings).

## Outputs

- `NormalizedTerm` results with canonical ids/labels, confidence, and known/unknown flags.

## Run and Validate

- `make test`
- `make contract-test`

## Dependencies

- Mapping data in `services/taxonomy/mappings`.
- Consumed by job extraction to `JobSpec` normalization flows in API handlers.

## Ownership and Status

- Owner: TBD
- Status: Active
