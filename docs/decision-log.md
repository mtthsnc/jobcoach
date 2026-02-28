# Decision Log

Record architecture and product decisions in ADR-lite format.

## Template

- Decision ID: `DEC-XXX`
- Date (UTC):
- Status: `proposed | accepted | deprecated`
- Context:
- Decision:
- Consequences:
- Alternatives considered:

---

- Decision ID: `DEC-001`
- Date (UTC): `2026-02-28`
- Status: `accepted`
- Context: Need continuity across context-window resets and multi-session execution.
- Decision: Use repo-local docs control system (`README`, `masterplan`, `implementation-plan`, `tasklist`, `NEXT_ACTION`, `work-log`) as canonical state.
- Consequences:
  - Lower context loss.
  - Slight documentation overhead per session.
- Alternatives considered:
  - Keep all state in chat only.
  - External project management tool as source of truth.

- Decision ID: `DEC-002`
- Date (UTC): `2026-02-28`
- Status: `accepted`
- Context: MVP must minimize hallucination and maximize traceability.
- Decision: Structured extraction with evidence spans and confidence scores is mandatory before downstream generation.
- Consequences:
  - Better reliability and auditability.
  - Added parser complexity.
- Alternatives considered:
  - Direct LLM summarization from raw text without evidence tracking.

- Decision ID: `DEC-003`
- Date (UTC): `2026-02-28`
- Status: `accepted`
- Context: No runtime framework dependencies are installed in the current environment.
- Decision: Implement M0-M1 infrastructure with dependency-free Python (`stdlib` + SQLite) as the baseline execution layer.
- Consequences:
  - Fast local execution and deterministic CI behavior.
  - Potential refactor later when adopting production framework/runtime.
- Alternatives considered:
  - Pause implementation until FastAPI/Celery stack is available.
  - Use mixed shell-only tooling without API runtime implementation.
