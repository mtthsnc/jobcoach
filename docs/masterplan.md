# Master Plan: AI Career and Interview Coaching System

## 1. Mission

Build an AI coaching platform that converts a real job posting and a candidate profile into:

- Role-specific mock interviews with adaptive follow-ups.
- Precise diagnosis of interview weaknesses.
- A measurable, personalized preparation roadmap.
- Persistent progress tracking across sessions.
- Negotiation and post-interview support.

## 2. Primary User Problem

Candidates prepare too broadly and cannot map their experience to specific hiring signals in a target role. They need a system that is grounded, personalized, and measurable.

## 3. Success Outcomes

- Candidate can articulate role fit clearly in 1-2 minutes.
- Competency scores improve over repeated mock sessions.
- Candidate has evidence-backed stories for each critical competency.
- Candidate receives an actionable prep plan with measurable checkpoints.
- Candidate gets practical support for negotiation and post-interview follow-up.

## 4. System Scope

### In scope

- Job posting ingestion from URL/text/document.
- Structured `JobSpec` extraction with confidence and evidence spans.
- Candidate profile parsing from CV and story notes.
- Adaptive interview generation and scoring.
- Gap detection and targeted feedback.
- Longitudinal progress tracking and trajectory planning.

### Out of scope for MVP

- Real-time voice analysis.
- ATS writeback integrations.
- Mentor collaboration workspaces.

## 5. Architecture (High Level)

- Ingestion layer: URL/text/document intake and cleaning.
- Extraction layer: structured job and candidate parsing.
- Intelligence layer: adaptive interview orchestration + scoring + gap analysis.
- Persistence layer: structured DB, object storage, event outbox.
- Experience layer: dashboard, reports, and planning UX.

## 6. Core Components

- Job extraction tool (Defuddle-like): cleaner + section parser + skill normalizer.
- Adaptive interview coach engine: question planner + follow-up controller + rubric scorer.
- Interview session state manager: turn history, competency trajectory, and reviewer override audit.

## 7. Data Contracts

Canonical entities:

- `JobSpec`
- `CandidateProfile`
- `InterviewSession`
- `FeedbackReport`
- `TrajectoryPlan`

Contract artifacts live in `schemas/openapi/` and `schemas/jsonschema/`.

## 8. Quality and Safety Constraints

- Structured extraction first, generation second.
- Every critical field has source evidence or explicit null.
- JSON schema validation on all core entities.
- Hallucination controls: no invented candidate claims.
- Confidence thresholds with reviewer override path.

## 9. Delivery Phases

- Phase M0: schemas, taxonomy, eval harness, workflow skeleton.
- Phase M1: job ingestion and `JobSpec` pipeline.
- Phase M2: candidate ingestion and storybank pipeline.
- Phase M3: interview orchestration and adaptive logic.
- Phase M4: scoring, feedback, and gap analytics.
- Phase M5: progress tracking and trajectory planning.
- Phase M6: negotiation and post-interview modules.

## 10. Milestone Exit Gates

- M0: Contracts validated in CI.
- M1: >= 90% valid `JobSpec` generation on benchmark set.
- M2: >= 85% valid candidate profile parse on benchmark set.
- M3: Interview relevance score >= 0.80 and session-schema validity >= 95%.
- M4: Every gap feedback item includes evidence and action.
- M5: Trend dashboard correctly computes improvement metrics.

## 11. Program Governance

- Backlog authority: `docs/tasklist.md`.
- Session continuity authority: `docs/session-continuity.md`.
- Decision authority: `docs/decision-log.md`.
- Current execution pointer: `docs/NEXT_ACTION.md`.
