# Contract Test Scaffold

This directory contains a lightweight contract-test harness that runs with
Python standard library only.

## Goals
- Validate that contract artifacts exist.
- Validate JSON schema artifacts are parseable and structurally sane.
- Perform basic OpenAPI text-level checks (version, paths, methods, operationIds).
- Stay dependency-free so it can run in CI without extra installs.

## Run Locally
```bash
make validate-openapi
make contract-test
python3 -m unittest discover -s tests/contracts -p "test_*.py" -v

# API contract tests (requires local API launch command)
JOBCOACH_API_CMD="python3 apps/api-gateway/serve.py" \
JOBCOACH_API_BASE_URL="http://127.0.0.1:8000" \
python3 -m unittest tests/contracts/test_job_ingestions_api_contract.py -v
```

CI uses the same flow: Makefile targets first, then the dependency-light
Python contract artifact checks.

## Notes
- This is scaffolding, not full semantic OpenAPI/JSON Schema validation.
- `make contract-test` runs migration smoke plus dependency-light contract tests.
- If/when external tooling is allowed, this can be extended with
  `openapi-spec-validator` and `jsonschema`.
- `test_job_ingestions_api_contract.py` is dependency-free and launches the local
  API process via `JOBCOACH_API_CMD`. It bootstraps a fresh SQLite schema from
  `infra/migrations/*.sql` for each run.
