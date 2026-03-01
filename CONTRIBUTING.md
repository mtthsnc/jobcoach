# Contributing

## Prerequisites

- Python `3.x` available as `python3`
- `make`

## Local Setup

```bash
make migrate-up
HOST=127.0.0.1 PORT=8000 JOBCOACH_DB_PATH=.tmp/migrate-local.sqlite3 python3 apps/api-gateway/serve.py
```

## Validation Before Opening a PR

```bash
make test
make validate-openapi
make migrate-up
make migrate-down
make contract-test
```

Optional Docker validation:

```bash
make docker-test
```

## Documentation Expectations

- Update docs when behavior, contracts, or workflows change.
- Keep `README.md` quickstart and command references accurate.
- Keep `docs/NEXT_ACTION.md` and `docs/work-log.md` aligned with active execution flow.

## Pull Request Checklist

- Add or update tests for behavior changes.
- Keep OpenAPI/JSON schema artifacts consistent with implementation.
- Ensure idempotency/versioning semantics remain deterministic.
- Include concise migration notes when schema changes are introduced.
