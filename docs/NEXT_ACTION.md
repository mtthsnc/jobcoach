# Next Action

## Active Milestone

`M6` (Product Roadmap)

## Active Task

- Task ID: `M6-003`
- Task: Implement negotiation strategy generator (anchor band, concession ladder, objection playbook) from context signals.
- Why now: `M6-002` established deterministic negotiation-context signals and schema-backed payload fields, enabling stable strategy synthesis over fixed context inputs.

## Exact Next Steps

1. Add deterministic strategy synthesis module that consumes `NegotiationPlan` context signals and emits `anchor_band`, concession ladder, and objection playbook sections.
2. Integrate generated strategy block into negotiation plan payload with explicit schema fields and deterministic ordering/tie-break rules.
3. Add fixture-driven unit tests to lock strategy ordering, bounded numeric outputs, and reproducibility for identical context histories.
4. Extend API/unit/contract tests to assert strategy fields are stable across regeneration/idempotent create flows and remain schema-valid.
5. Run `make validate-openapi`, `make migrate-up`, `make migrate-down`, `make test`, and `make contract-test`.

## Validation Required

- Confirm planning artifacts are coherent and actionable:
  - Strategy output is deterministic for fixed context fixtures.
  - Negotiation plan payload remains schema-valid after strategy integration.
  - Unit/contract suites assert stable strategy ordering and bounded outputs.
  - `docs/work-log.md` records M6-003 execution evidence.

## Return Pointer

After `M6-003` is complete, advance pointer to `M6-004`.
