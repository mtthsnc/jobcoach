Purpose: deterministic interview question planning and adaptive sequencing primitives for M3.

Current module:
- `planner.py`: deterministic opening-question planner using `JobSpec` competency weights and `CandidateProfile` coverage evidence.
- `followup.py`: adaptive follow-up selector using prior-turn score and competency-gap prioritization.
