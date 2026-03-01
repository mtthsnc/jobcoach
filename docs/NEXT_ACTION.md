# Next Action

## Active Milestone

`M8` (Operational Hardening)

## Active Task

- Task ID: `M8-004`
- Task: Shift eval execution to asynchronous worker orchestration (`queued` -> `running` -> terminal) backed by outbox relay flow.
- Why now: `M8-003` relay reliability is complete, so async worker-driven eval lifecycle transitions are now the critical dependency for `M8-005` readiness and latency gates.

## Exact Next Steps

1. Add async eval execution queueing path:
   - ensure `POST /evals/run` enqueues deterministic work items and returns queued acknowledgement without synchronous benchmark execution,
   - preserve idempotency-key semantics for replay-safe queued responses.
2. Implement eval worker transitions:
   - worker picks queued eval runs deterministically,
   - transitions `queued -> running -> terminal` with persisted timestamps/metrics/error metadata,
   - emits lifecycle outbox events through existing relay-compatible flow.
3. Add worker/orchestration tests and fixtures:
   - cover queued acknowledgement, worker-driven running/terminal transitions, and failure recovery,
   - assert deterministic replay safety across duplicate submissions and repeated worker polls.
4. Run validation and record handoff:
   - execute targeted tests plus full gates (`make test`, `make validate-openapi`, migrate up/down, `make contract-test`),
   - append START/END execution evidence in `docs/work-log.md`,
   - move pointer to `M8-005` after acceptance criteria pass.

## Validation Required

- Confirm `M8-004` acceptance criteria:
  - `POST /evals/run` returns deterministic queued acknowledgement without synchronous benchmark execution.
  - Eval runs transition through persisted async worker states (`queued`, `running`, terminal) with deterministic metadata.
  - Lifecycle outbox events remain deterministic and relay-compatible under worker-driven execution.
  - Validation evidence is captured in `docs/work-log.md`.

## Return Pointer

After `M8-004` is complete, execute `M8-005`.
