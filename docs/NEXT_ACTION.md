# Next Action

## Active Milestone

`M8` (Operational Hardening)

## Active Task

- Task ID: `M8-005`
- Task: Add runtime health/readiness probes and API read-path latency benchmark gate (`p95 <= 400ms`).
- Why now: `M8-004` async eval orchestration is complete, so readiness observability and read-path latency enforcement are now the next blocking dependency for operational hardening.

## Exact Next Steps

1. Implement explicit runtime probe surfaces:
   - keep `/health` deterministic for liveness semantics,
   - add/readiness behavior that verifies essential runtime dependencies (DB connectivity + core process readiness) with stable response envelopes.
2. Add read-path latency benchmark gate:
   - define deterministic read-path request corpus across implemented GET endpoints,
   - enforce `p95 <= 400ms` threshold and emit machine-readable benchmark report.
3. Add unit/contract coverage for probe and latency instrumentation:
   - assert readiness success/failure semantics and non-flaky probe envelopes,
   - verify benchmark gate fails deterministically on threshold regressions.
4. Run validation and record handoff:
   - execute targeted tests plus full gates (`make test`, `make validate-openapi`, migrate up/down, `make contract-test`),
   - append START/END execution evidence in `docs/work-log.md`,
   - move pointer to `M8-006` after acceptance criteria pass.

## Validation Required

- Confirm `M8-005` acceptance criteria:
  - Runtime health/readiness probe behavior is deterministic and suitable for operational checks.
  - Read-path latency benchmark gate is implemented with enforced `p95 <= 400ms` threshold.
  - Validation suite includes probe + latency evidence and remains green.
  - Validation evidence is captured in `docs/work-log.md`.

## Return Pointer

After `M8-005` is complete, execute `M8-006`.
