# services/quality-eval

## Purpose

Quality gates for contract validation and deterministic benchmark scoring.

## Modules

- `schema_validation/validator.py`: JSON schema validation helpers used by contract and benchmark checks.
- `benchmark/extraction_benchmark.py`: extraction quality threshold runner.
- `benchmark/candidate_parse_benchmark.py`: candidate parsing quality threshold runner.
- `benchmark/interview_relevance_benchmark.py`: interview relevance quality threshold runner.
- `benchmark/feedback_quality_benchmark.py`: feedback quality threshold runner.
- `benchmark/trajectory_quality_benchmark.py`: trajectory/dashboard quality threshold runner.
- `benchmark/negotiation_quality_benchmark.py`: negotiation/follow-up quality threshold runner.
- `benchmark/eval_orchestration_benchmark.py`: eval-run orchestration reliability threshold runner.

## Inputs

- Benchmark fixture datasets under `tests/unit/fixtures`.
- Canonical contract artifacts (`schemas/openapi/openapi.yaml`, `schemas/jsonschema/core-schemas.json`).

## Outputs

- Deterministic pass/fail benchmark reports written to `.tmp/*.json`.
- Validation issues for schema and contract conformance.

## Run and Validate

- `make test`
- `make validate-openapi`
- `make benchmark-extraction`
- `make benchmark-candidate-parse`
- `make benchmark-interview-relevance`
- `make benchmark-feedback-quality`
- `make benchmark-trajectory-quality`
- `make benchmark-negotiation-quality`
- `make benchmark-eval-orchestration`
- `make docker-test`

## Dependencies

- Benchmarks import service modules across `services/`.
- Used by CI/local quality gates and contract validation workflows.

## Ownership and Status

- Owner: TBD
- Status: Active
