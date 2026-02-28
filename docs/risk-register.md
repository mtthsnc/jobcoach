# Risk Register

## Scoring

- Likelihood: `Low | Medium | High`
- Impact: `Low | Medium | High`
- Exposure: qualitative judgement from likelihood x impact.

## Risks

| ID | Risk | Likelihood | Impact | Exposure | Mitigation | Owner | Status |
|---|---|---|---|---|---|---|---|
| R-001 | Hallucinated extraction or feedback claims | Medium | High | High | Evidence spans + schema validation + confidence gating | Platform | Open |
| R-002 | Weak parsing for noisy job pages | High | Medium | High | Multi-pass extraction and manual review patch endpoint | Job Extraction | Open |
| R-003 | Inconsistent candidate data quality | High | Medium | High | Data quality flags + guided correction loop | Candidate Profile | Open |
| R-004 | Pipeline retries cause duplicate writes | Medium | Medium | Medium | Idempotency keys + unique constraints + outbox pattern | Orchestrator | Open |
| R-005 | Slow execution due to over-scoped M0-M2 | Medium | Medium | Medium | Enforce strict milestone gates and defer non-MVP scope | Tech Lead | Open |
| R-006 | PII leakage in logs/artifacts | Low | High | Medium | Structured redaction policy and sensitive-field handling | Security | Open |
