# Next Action

## Active Milestone

`M6` (Product Roadmap)

## Active Task

- Task ID: `M6-005`
- Task: Persist/retrieve negotiation plans with idempotent regeneration + optimistic version checks.
- Why now: `M6-004` completed deterministic strategy and follow-up generation blocks; persistence semantics now need version progression and conflict-safe regeneration.

## Exact Next Steps

1. Extend negotiation plan create semantics with `expected_version` and `regenerate` request controls for optimistic conflict detection and explicit regeneration.
2. Add repository versioning workflow for `NegotiationPlan` by `(candidate_id, target_role)` with idempotent replay/conflict behavior and supersede linkage.
3. Update negotiation contracts/schemas to include version metadata and supersession fields required for retrieval and replay stability.
4. Add unit/contract coverage for first-create, replay, regenerate progression, and stale expected-version conflicts while preserving schema validity.
5. Run `make validate-openapi`, `make migrate-up`, `make migrate-down`, `make test`, and `make contract-test`.

## Validation Required

- Confirm planning artifacts are coherent and actionable:
  - Versioned negotiation plans persist/retrieve correctly with deterministic payload blocks unchanged on replay.
  - Regeneration increments version and sets supersedes linkage while preserving schema validity.
  - Unit/contract suites assert idempotent replay, expected-version conflicts, and retrieval semantics.
  - `docs/work-log.md` records M6-005 execution evidence.

## Return Pointer

After `M6-005` is complete, advance pointer to `M6-006`.
