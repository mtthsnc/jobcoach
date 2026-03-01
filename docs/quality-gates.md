# Quality Gates

JobCoach enforces deterministic benchmark thresholds in local validation and CI.

## Benchmark Threshold Defaults

- Extraction benchmark:
  - `role_title_accuracy >= 0.90`
  - `section_coverage >= 0.90`
  - `skill_precision >= 0.80`
  - `skill_recall >= 0.80`
  - `jobspec_valid_rate >= 0.90`
- Candidate parse benchmark:
  - `candidate_profile_valid_rate >= 0.95`
  - `required_field_coverage >= 0.90`
  - `story_quality_p50 >= 0.70`
  - `story_quality_p10 >= 0.65`
- Interview relevance benchmark:
  - `overall_relevance >= 0.90`
  - plus coverage/alignment/non-repetition/difficulty bounds
- Feedback quality benchmark:
  - `overall_feedback_quality >= 0.90`
  - plus completeness/root-cause/evidence/rewrite/action-plan checks
- Eval orchestration benchmark:
  - `transition_correctness_rate >= 1.00`
  - `idempotency_correctness_rate >= 1.00`
  - `lifecycle_event_integrity_rate >= 1.00`
  - `overall_eval_orchestration_quality >= 1.00`

## Testing Strategy

- Unit tests validate deterministic service behavior.
- Contract tests validate schema artifacts and OpenAPI structure.
- API contract tests launch a local API process against a fresh SQLite schema.

## Validation Commands

Standard local gate sequence:

```bash
make test
make validate-openapi
make migrate-up
make migrate-down
make contract-test
```

Containerized validation:

```bash
make docker-test
```
