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

- Decision ID: `DEC-010`
- Date (UTC): `2026-02-28`
- Status: `accepted`
- Context: M6 scope ("negotiation and post-interview support") is broad and could sprawl across contracts, strategy generation, follow-up content, and persistence unless decomposed with the same deterministic pattern used in M3-M5.
- Decision: Decompose M6 into six tasks (`M6-001`..`M6-006`) in contract-first order: negotiation plan API/storage foundation, deterministic negotiation-context aggregation, strategy generation, post-interview follow-up planning, versioned persistence semantics, then benchmark threshold gating.
- Consequences:
  - M6 has a single executable critical path with explicit acceptance gates and lower integration risk.
  - Negotiation/follow-up output quality gates are deferred until core contract and orchestration behavior is stable.
- Alternatives considered:
  - Implement M6 as one bundled epic with mixed contract/generation work.
  - Start with follow-up templates before contract and persistence foundations are in place.

- Decision ID: `DEC-011`
- Date (UTC): `2026-02-28`
- Status: `accepted`
- Context: M6 execution needed a stable API/storage foundation for negotiation and post-interview support before introducing derived signal logic and strategy generation.
- Decision: Introduce `NegotiationPlan` as the M6 anchor contract (`POST/GET /negotiation-plans`) with schema-validated deterministic payloads and idempotent persistence semantics.
- Consequences:
  - Downstream M6 tasks can build on a fixed persisted entity and contract-tested API surface.
  - Initial negotiation payload content is intentionally baseline and will be expanded by subsequent deterministic aggregation/generation tasks.
- Alternatives considered:
  - Delay contract/storage work and begin with free-form negotiation generation logic.
  - Extend `TrajectoryPlan` instead of introducing a dedicated M6 negotiation entity.

- Decision ID: `DEC-012`
- Date (UTC): `2026-03-01`
- Status: `accepted`
- Context: M6-002 required deterministic negotiation context from heterogeneous inputs (offer targets, interview/feedback progression, and trajectory readiness) while keeping API payloads contract-safe.
- Decision: Introduce a dedicated deterministic negotiation-context aggregator module and expose its output through structured `NegotiationPlan` fields (`compensation_targets` with bounded adjustment metadata, `leverage_signals`, `risk_signals`, `evidence_links`).
- Consequences:
  - Negotiation payload generation now has stable, fixture-testable signal math and ordering for identical histories.
  - Downstream M6 strategy/follow-up generators can consume normalized context primitives instead of re-deriving history signals.
- Alternatives considered:
  - Keep negotiation context logic embedded directly in API handlers without a dedicated module.
  - Keep only free-form talking points without explicit leverage/risk/evidence structures in schema contracts.

- Decision ID: `DEC-013`
- Date (UTC): `2026-03-01`
- Status: `accepted`
- Context: M6-003 required deterministic synthesis of negotiation tactics from normalized context signals so strategy outputs remain stable across idempotent regeneration and contract validation.
- Decision: Introduce a dedicated deterministic negotiation strategy generator and persist structured strategy fields on `NegotiationPlan` (`anchor_band`, `concession_ladder`, `objection_playbook`) with explicit schema contracts and fixture-driven tests.
- Consequences:
  - Negotiation strategy outputs are now reproducible for fixed context histories and auditable through explicit evidence-bearing strategy structures.
  - Contract/core schema surface area increased, requiring downstream M6-004 follow-up planning to integrate with the new strategy blocks.
- Alternatives considered:
  - Keep strategy derivation inline in API handlers without a dedicated module.
  - Keep only free-form `strategy_summary` and talking points without structured ladder/playbook contracts.

- Decision ID: `DEC-014`
- Date (UTC): `2026-03-01`
- Status: `accepted`
- Context: M6-004 needed deterministic post-interview follow-up content (thank-you guidance, recruiter cadence, and outcome branches) without introducing non-repeatable drafting variance.
- Decision: Add a dedicated deterministic negotiation follow-up planner and persist structured `NegotiationPlan.follow_up_plan` blocks (`thank_you_note`, `recruiter_cadence`, `outcome_branches`) alongside bounded, deterministic `follow_up_actions`.
- Consequences:
  - Follow-up outputs are now schema-validated, branch-ordered, day-bounded, and reproducible for fixed strategy/context inputs.
  - Negotiation contract surface area increased, and downstream M6-005 versioning must preserve the expanded follow-up structure across replay/regeneration flows.
- Alternatives considered:
  - Keep only free-form `follow_up_actions` templates without structured follow-up planning blocks.
  - Generate follow-up copy inline in API handlers instead of a dedicated deterministic planner module.

- Decision ID: `DEC-015`
- Date (UTC): `2026-03-01`
- Status: `accepted`
- Context: M6-005 required negotiation persistence semantics to support replay-safe regeneration and stale-write prevention, matching the versioned model already used for feedback and trajectory entities.
- Decision: Version `NegotiationPlan` per `(candidate_id, target_role)` with optional `expected_version` and `regenerate` request controls, idempotent key replay/conflict handling, and `supersedes_negotiation_plan_id` linkage.
- Consequences:
  - Negotiation plan create/get flows are now conflict-safe and auditable across regeneration cycles.
  - M6 contract and migration surface area increased (`version`, `supersedes_negotiation_plan_id`, request version fields), requiring M6-006 benchmarks to validate versioned outputs in quality gates.
- Alternatives considered:
  - Keep a single mutable negotiation row per candidate/role and overwrite in place.
  - Rely on idempotency keys only without explicit version progression and optimistic conflict checks.
