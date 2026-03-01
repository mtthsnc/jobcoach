# services/orchestrator

## Purpose

Workflow orchestration namespace for cross-service execution plumbing.

## Modules

- `outbox/`: orchestration support area for outbox/event flow integration.

## Inputs

- Orchestration events and persistence-side triggers from API mutation flows.

## Outputs

- Deterministic event dispatch scaffolding for asynchronous or decoupled processing paths.

## Run and Validate

- `make test`
- `make contract-test`

## Dependencies

- Shared outbox/event abstractions in `packages/eventing`.
- SQLite persistence and migration contracts in `packages/db` and `infra/migrations`.

## Ownership and Status

- Owner: TBD
- Status: Scaffold (integration surface present, runtime workflow modules are minimal)
