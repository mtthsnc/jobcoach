# JobCoach

JobCoach is an API-first, deterministic AI coaching backend for role-targeted interview preparation.

## Table of Contents

- [Why JobCoach](#why-jobcoach)
- [Start Here](#start-here)
- [Choose Your Path](#choose-your-path)
- [Architecture](#architecture)
- [Monorepo Layout](#monorepo-layout)
- [Developer Commands](#developer-commands)
- [Documentation Map](#documentation-map)
- [Project Status](#project-status)
- [Contributing](#contributing)
- [Security](#security)
- [License](#license)

## Why JobCoach

Most candidates prepare too broadly. JobCoach is built to keep preparation:

- Role-grounded: starts from a real job description.
- Candidate-grounded: starts from CV experience and story notes.
- Measurable: tracks competency-level movement over sessions.
- Actionable: produces gaps, rewrites, and preparation plans.

## Start Here

### Local (fastest path)

Prerequisites:

- Python `3.x` available as `python3`
- `make`

```bash
make migrate-up
HOST=127.0.0.1 PORT=8000 JOBCOACH_DB_PATH=.tmp/migrate-local.sqlite3 python3 apps/api-gateway/serve.py
```

Smoke test:

```bash
curl -sS -X POST http://127.0.0.1:8000/v1/job-ingestions \
  -H 'content-type: application/json' \
  -H 'Idempotency-Key: demo-job-1' \
  -d '{"source_type":"text","source_value":"Senior Backend Engineer\nResponsibilities:\n- Build reliable APIs\nRequirements:\n- Python\n- SQL"}'
```

### Docker

Prerequisites:

- Docker Engine + Docker Compose plugin

```bash
make docker-up
make docker-url
make docker-test
make docker-down
```

By default, Docker publishes the container on a random free host port so it
does not clash with services already using `8000`. If you need a fixed host
port, set one explicitly:

```bash
DOCKER_HOST_PORT=8000 make docker-up
```

## Choose Your Path

- Evaluate the API quickly:
  - Start with the local quickstart above, then see endpoint details in [`docs/api-surface.md`](docs/api-surface.md).
- Build features in the backend:
  - Use developer commands below and contribution flow in [`CONTRIBUTING.md`](CONTRIBUTING.md).
- Understand architecture and execution history:
  - Start with [`docs/README.md`](docs/README.md), then `masterplan`, `implementation-plan`, and `tasklist`.

## Architecture

High-level flow:

`Ingestion -> Extraction/Parsing -> Interview Engine -> Feedback -> Progress Tracking -> Trajectory Planning`

Design principles:

- Contracts-first: OpenAPI + JSON Schema are source-of-truth.
- Deterministic behavior over unconstrained generation.
- Evidence-linked outputs with confidence metadata.
- Idempotent mutation semantics and optimistic version checks where relevant.

Core contract entities:

- `JobSpec`
- `CandidateProfile`
- `InterviewSession`
- `FeedbackReport`
- `TrajectoryPlan`

Canonical contract artifacts:

- `schemas/openapi/openapi.yaml`
- `schemas/jsonschema/core-schemas.json`

## Monorepo Layout

```text
apps/
  api-gateway/
services/
  job-extraction/
  taxonomy/
  candidate-profile/
  interview-engine/
  progress-tracking/
  trajectory-planning/
  quality-eval/
  orchestrator/
packages/
  db/
  eventing/
  contracts/
schemas/
  openapi/
  jsonschema/
infra/
  migrations/
tests/
  unit/
  contracts/
docs/
```

## Developer Commands

Show all available targets:

```bash
make help
```

Primary commands:

- `make test`
- `make validate-openapi`
- `make contract-test`
- `make docker-test`
- `make migrate-up`
- `make migrate-down`

Benchmark-specific commands:

- `make benchmark-extraction`
- `make benchmark-candidate-parse`
- `make benchmark-interview-relevance`
- `make benchmark-feedback-quality`
- `make benchmark-trajectory-quality`
- `make benchmark-negotiation-quality`
- `make benchmark-eval-orchestration`
- `make benchmark-api-read-latency`

Detailed quality thresholds and validation strategy: [`docs/quality-gates.md`](docs/quality-gates.md).

## Documentation Map

- Documentation hub and runbook: [`docs/README.md`](docs/README.md)
- API endpoints and contract wiring status: [`docs/api-surface.md`](docs/api-surface.md)
- Quality gates and benchmark thresholds: [`docs/quality-gates.md`](docs/quality-gates.md)
- Persistence, idempotency, and versioning behavior: [`docs/persistence-versioning.md`](docs/persistence-versioning.md)
- Roadmap and continuity:
  - `docs/masterplan.md`
  - `docs/implementation-plan.md`
  - `docs/tasklist.md`
  - `docs/NEXT_ACTION.md`
  - `docs/work-log.md`

## Project Status

As of `2026-02-28`, milestones `M0` through `M4` are complete, `M5` is active, and `M6` is planned.

Roadmap summary:

- `M0`: Foundations (contracts, schema validation, migrations, outbox) ✅
- `M1`: Job ingestion and extraction ✅
- `M2`: Candidate parsing and storybank ✅
- `M3`: Adaptive interview orchestration ✅
- `M4`: Feedback and gap analytics ✅
- `M5`: Progress tracking and trajectory intelligence (active)
- `M6`: Negotiation and post-interview support (planned)

## Contributing

See [`CONTRIBUTING.md`](CONTRIBUTING.md).

## Security

See [`SECURITY.md`](SECURITY.md).

## License

No license file is currently present in this repository.
