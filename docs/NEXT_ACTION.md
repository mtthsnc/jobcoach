# Next Action

## Active Milestone

`M8` (Planning)

## Active Task

- Task ID: `M8-PLAN-001`
- Task: Define executable M8 backlog with dependencies and acceptance criteria.
- Why now: `M7-CLOSE-001` is complete with final validation evidence and release notes recorded, so the next critical path is planning M8 into concrete executable tasks.

## Exact Next Steps

1. Define M8 implementation scope and sequence:
   - identify M8 objective and contract/runtime surfaces from current roadmap,
   - break scope into executable tasks (`M8-001`..`M8-00N`) with dependency ordering.
2. Update planning artifacts:
   - add M8 tasks to `docs/tasklist.md` with priority, dependencies, and explicit acceptance criteria,
   - ensure only `M8-PLAN-001` is closed when the task graph is complete.
3. Record planning decisions + handoff:
   - document planning rationale in `docs/decision-log.md` if task boundaries or ordering introduce new architectural/operational decisions,
   - append START/END evidence in `docs/work-log.md`,
   - move pointer to the first executable M8 task after plan completion.

## Validation Required

- Confirm M8 planning artifacts are complete and actionable:
  - `docs/tasklist.md` contains a complete M8 task graph with dependencies and acceptance criteria.
  - The first executable M8 task is clearly identified and set as next pointer.
  - `docs/work-log.md` captures planning execution evidence.
  - Any significant planning/architecture rationale is logged in `docs/decision-log.md`.

## Return Pointer

After `M8-PLAN-001` is complete, execute the first executable M8 implementation task.
