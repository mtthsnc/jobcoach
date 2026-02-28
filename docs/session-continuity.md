# Session Continuity Protocol

Use this protocol whenever a session starts or ends. Goal: zero context loss.

## Start-of-Session Checklist

1. Read, in order:
- `docs/README.md`
- `docs/NEXT_ACTION.md`
- `docs/tasklist.md`
- `docs/work-log.md` (latest 10 entries)
- `docs/decision-log.md`

2. Confirm the active task:
- Continue the item marked in `docs/NEXT_ACTION.md`.
- If it conflicts with `docs/tasklist.md`, fix `docs/NEXT_ACTION.md` first.

3. Write a start log entry in `docs/work-log.md`:
- Timestamp (UTC)
- Session goal
- Task ID
- Planned validation steps

## End-of-Session Checklist

1. Update modified docs/code.
2. Update task status in `docs/tasklist.md`.
3. Update `docs/NEXT_ACTION.md` with exact next step.
4. Append end log entry in `docs/work-log.md`:
- What was completed
- What remains
- Risks/blockers
- Validation evidence

5. If architecture/product decisions changed, append to `docs/decision-log.md`.

## Hard Rules

- Never leave `docs/NEXT_ACTION.md` stale.
- Never close a session without an end log entry.
- Never mark `DONE` without test or validation evidence.
- Keep docs in sync with reality; avoid aspirational status.

## Handoff Quality Bar

A new session should be able to continue in under 5 minutes without reading chat history.
