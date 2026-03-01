# Next Action

## Active Milestone

`M8` (Operational Hardening)

## Active Task

- Task ID: `M8-003`
- Task: Implement outbox relay worker with bounded retry/backoff, publish-attempt tracking, and dead-letter semantics.
- Why now: `M8-002` observability/redaction guardrails are complete, so relay reliability is the next prerequisite for async eval orchestration in `M8-004`.

## Exact Next Steps

1. Add relay worker execution path over `outbox_events`:
   - dequeue publish-eligible rows deterministically,
   - publish through a relay abstraction with idempotent event handling,
   - mark success transitions atomically with publish timestamps.
2. Implement failure-path state transitions:
   - track `publish_attempts` and `last_error`,
   - apply bounded retry policy with deterministic backoff/jitter policy (or fixed deterministic schedule),
   - move permanently failing rows to dead-letter terminal state after retry exhaustion.
3. Add reliability tests and fixtures:
   - cover happy-path publish, transient retry recovery, and retry-exhausted dead-letter outcomes,
   - assert deterministic state transitions and replay safety under repeated worker runs.
4. Run validation and record handoff:
   - execute targeted tests plus full gates (`make test`, `make validate-openapi`, migrate up/down, `make contract-test`),
   - append START/END execution evidence in `docs/work-log.md`,
   - move pointer to `M8-004` after acceptance criteria pass.

## Validation Required

- Confirm `M8-003` acceptance criteria:
  - Pending outbox events publish deterministically through relay worker execution.
  - Retry-safe state transitions update publish attempts and next-attempt scheduling correctly.
  - Retry exhaustion transitions events to dead-letter state with deterministic terminal metadata.
  - Validation evidence is captured in `docs/work-log.md`.

## Return Pointer

After `M8-003` is complete, execute `M8-004`.
