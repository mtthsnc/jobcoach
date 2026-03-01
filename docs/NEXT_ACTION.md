# Next Action

## Active Milestone

`M6` (Product Roadmap)

## Active Task

- Task ID: `M6-006`
- Task: Add negotiation/follow-up quality benchmark + threshold gates for CI/local.
- Why now: `M6-005` delivered versioned negotiation persistence semantics; quality gating now needs to lock negotiation strategy and follow-up output regressions.

## Exact Next Steps

1. Define negotiation/follow-up benchmark fixtures that cover high-leverage, high-risk, and low-signal histories with deterministic expected outputs.
2. Implement benchmark runner metrics for strategy structure quality, follow-up cadence quality, branch/action boundedness, and evidence-link consistency.
3. Add benchmark threshold gates to local/CI validation flow and emit report artifacts under `.tmp/`.
4. Add/extend tests to assert benchmark report schema and threshold failure behavior.
5. Run `make test` and `make contract-test` with benchmark gate enabled and record evidence in `docs/work-log.md`.

## Validation Required

- Confirm planning artifacts are coherent and actionable:
  - Benchmark report includes deterministic quality metrics for negotiation strategy and follow-up outputs.
  - Threshold gates fail on fixture regressions and pass on baseline fixtures.
  - CI/local flows invoke the benchmark gate consistently.
  - `docs/work-log.md` records M6-006 execution evidence.

## Return Pointer

After `M6-006` is complete, close M6 milestone and prepare next milestone planning pointer.
