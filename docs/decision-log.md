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

- Decision ID: `DEC-004`
- Date (UTC): `2026-02-28`
- Status: `accepted`
- Context: M5 scope (progress tracking + trajectory planning) crosses contracts, storage, deterministic analytics, and quality gates; execution order must stay deterministic to avoid rework.
- Decision: Decompose M5 into six tasks (`M5-001`..`M5-006`) in contract-first order: endpoints/storage, trend aggregation, planner generation, versioned persistence semantics, dashboard read model, then benchmark gating.
- Consequences:
  - M5 execution has a single critical path with explicit dependencies and acceptance checks.
  - Benchmark gating is delayed until read-model behavior stabilizes, reducing false-negative threshold churn.
- Alternatives considered:
  - Implement M5 as a single bundled epic.
  - Start from dashboard/read-model outputs before hardening contracts and storage semantics.

- Decision ID: `DEC-005`
- Date (UTC): `2026-02-28`
- Status: `accepted`
- Context: Longitudinal progress metrics blend interview-session and feedback-report histories that may overlap in time and completeness; unstable ordering/fallback rules would create nondeterministic trajectory outputs.
- Decision: Compute progress snapshots in deterministic timestamp/source order, with interview-score fallback derived from question history, and produce baseline/current/delta competency trends with stable tie-break sorting.
- Consequences:
  - Trend metrics are repeatable for fixed histories and safe to use as downstream planner inputs.
  - Empty/partial histories return explicit zero-snapshot summaries rather than ad hoc null heuristics.
- Alternatives considered:
  - Use latest feedback report only for trend metrics.
  - Use non-deterministic ranking of competencies when deltas tie.

- Decision ID: `DEC-006`
- Date (UTC): `2026-02-28`
- Status: `accepted`
- Context: Trajectory outputs must convert trend metrics into actionable plans while remaining deterministic across idempotent regeneration and contract validation.
- Decision: Introduce a deterministic trajectory planner that ranks competency gaps using target-role expectations plus trend risk, then generates bounded weekly actions with explicit evidence tokens (`current=`, `target=`, `delta=`) and date-ordered milestones.
- Consequences:
  - Trajectory plan generation is repeatable for fixed inputs and explicitly traceable to underlying trend evidence.
  - Plan language is now coupled to deterministic templates, reducing stylistic variance but improving regression stability.
- Alternatives considered:
  - Keep static milestone/weekly templates and attach progress summary only.
  - Use unconstrained natural-language generation for weekly actions without deterministic evidence linkage.

- Decision ID: `DEC-007`
- Date (UTC): `2026-02-28`
- Status: `accepted`
- Context: Trajectory generation now produces deterministic plans, but persistence needed explicit version progression to support regeneration workflows and stale-write protection.
- Decision: Version trajectory plans per `(candidate_id, target_role)` with optimistic `expected_version` checks, idempotent key replay/conflict behavior, and supersede linkage to prior plan versions.
- Consequences:
  - Regenerated trajectory plans are auditable and conflict-safe under concurrent clients.
  - API/contracts and migration surface area increased (`version`, `supersedes_trajectory_plan_id`, request version fields).
- Alternatives considered:
  - Keep single trajectory row per candidate/role and overwrite payload in place.
  - Depend only on idempotency-key replay without explicit version progression or optimistic conflict checks.

- Decision ID: `DEC-008`
- Date (UTC): `2026-02-28`
- Status: `accepted`
- Context: The candidate dashboard needed a stable read model that combines longitudinal progress with the latest trajectory generation context without forcing clients to reconcile multiple APIs.
- Decision: Add `GET /candidates/{candidate_id}/progress-dashboard` with deterministic top-improving/top-risk competency cards, readiness signals, and latest trajectory metadata (including `version` and supersedes linkage), optionally scoped by `target_role`.
- Consequences:
  - Dashboard consumers receive deterministic ordering and version-safe trajectory context in a single response.
  - Contract and core schema surface area increased for dashboard-specific payload objects.
- Alternatives considered:
  - Compute dashboard cards client-side from `TrajectoryPlan.progress_summary`.
  - Expose only progress summary and omit trajectory metadata from dashboard responses.

- Decision ID: `DEC-009`
- Date (UTC): `2026-02-28`
- Status: `accepted`
- Context: M5 trajectory/dashboard logic is now deterministic, but regression protection required a dedicated quality gate that covers trend-card math, readiness signals, and trajectory/dashboard consistency in CI.
- Decision: Add a deterministic trajectory quality benchmark suite (fixtures for improving, declining, and empty-history candidates with versioned trajectory context) and enforce threshold gates through `make test` and CI reporting.
- Consequences:
  - Regressions in trend-metric ordering, readiness composition, schema validity, or trajectory metadata consistency fail fast in local and CI runs.
  - Benchmark maintenance overhead increases when trajectory/read-model logic intentionally changes.
- Alternatives considered:
  - Rely only on endpoint unit/contract tests without a benchmark gate.
  - Gate only trajectory planner output quality and omit dashboard consistency checks.
