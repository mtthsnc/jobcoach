# Next Action

## Active Milestone

`M8` (Operational Hardening)

## Active Task

- Task ID: `M8-006`
- Task: Document and enforce data-retention/redaction operations runbook for sensitive artifacts and logs.
- Why now: `M8-005` runtime readiness and read-path latency gates are complete, so sensitive-artifact retention/redaction operational controls are now the next blocking dependency before milestone closeout.

## Exact Next Steps

1. Define retention/redaction policy scope and runbook artifacts:
   - catalog sensitive stores/artifacts (DB rows, outbox payloads, logs, benchmark artifacts, temp files),
   - specify retention windows, deletion/redaction procedures, and operator ownership/escalation flows.
2. Implement enforcement checks and deterministic verification:
   - add automated checks/scripts/tests for expiry/redaction behavior on representative sensitive artifacts,
   - ensure checks are deterministic and runnable in local/CI validation flows.
3. Add unit/contract/documentation coverage:
   - validate runbook references and operational commands remain in sync with implemented behavior,
   - assert failure modes are actionable and do not leak sensitive payloads.
4. Run validation and record handoff:
   - execute targeted tests plus full gates (`make test`, `make validate-openapi`, migrate up/down, `make contract-test`),
   - append START/END execution evidence in `docs/work-log.md`,
   - move pointer to `M8-CLOSE-001` after acceptance criteria pass.

## Validation Required

- Confirm `M8-006` acceptance criteria:
  - Data-retention/redaction runbook for sensitive artifacts/logs is committed and operationally actionable.
  - Automated enforcement checks validate retention expiry/redaction behavior deterministically.
  - Validation suite includes retention/redaction enforcement evidence and remains green.
  - Validation evidence is captured in `docs/work-log.md`.

## Return Pointer

After `M8-006` is complete, execute `M8-CLOSE-001`.
