# services/candidate-profile

Purpose: deterministic candidate-profile parsing and retrieval support for M2 ingestion flow.
Owner: TBD
Status: active in M2-004.

## Current Responsibilities

- Parse candidate CV input (`cv_text` or `cv_document_ref`) into schema-aligned `CandidateProfile` payloads.
- Extract summary, structured experience timeline records, and scored skill signals.
- Generate STAR-structured storybank entries with competency tagging and evidence-quality scores.
- Provide deterministic parsing behavior suitable for fixture-based regression tests.
