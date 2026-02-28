-- Migration 005: M3 interview session foundations
-- Up Strategy: Create interview session state + response log tables with idempotent response ingestion support.
-- Down Strategy: Drop response log first, then interview sessions.

-- +goose Up
CREATE TABLE interview_sessions (
    session_id TEXT PRIMARY KEY,
    job_spec_id TEXT NOT NULL REFERENCES job_specs (job_spec_id) ON DELETE CASCADE,
    candidate_id TEXT NOT NULL REFERENCES candidate_profiles (candidate_id) ON DELETE CASCADE,
    mode TEXT NOT NULL DEFAULT 'mock_interview' CHECK (mode IN ('mock_interview', 'drill', 'negotiation')),
    status TEXT NOT NULL DEFAULT 'in_progress' CHECK (status IN ('in_progress', 'completed')),
    questions_json TEXT NOT NULL,
    scores_json TEXT NOT NULL,
    overall_score REAL NOT NULL DEFAULT 0 CHECK (overall_score BETWEEN 0 AND 100),
    root_cause_tags_json TEXT,
    version INTEGER NOT NULL DEFAULT 1 CHECK (version >= 1),
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_interview_sessions_job_spec_id ON interview_sessions (job_spec_id);
CREATE INDEX idx_interview_sessions_candidate_id ON interview_sessions (candidate_id);
CREATE INDEX idx_interview_sessions_status ON interview_sessions (status);

CREATE TABLE interview_session_responses (
    response_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES interview_sessions (session_id) ON DELETE CASCADE,
    idempotency_key TEXT NOT NULL,
    request_json TEXT NOT NULL,
    question_id TEXT NOT NULL,
    response_text TEXT NOT NULL,
    score REAL NOT NULL CHECK (score BETWEEN 0 AND 100),
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (session_id, idempotency_key)
);

CREATE INDEX idx_interview_session_responses_session_id_created_at
    ON interview_session_responses (session_id, created_at);

-- +goose Down
DROP INDEX IF EXISTS idx_interview_session_responses_session_id_created_at;
DROP TABLE IF EXISTS interview_session_responses;

DROP INDEX IF EXISTS idx_interview_sessions_status;
DROP INDEX IF EXISTS idx_interview_sessions_candidate_id;
DROP INDEX IF EXISTS idx_interview_sessions_job_spec_id;
DROP TABLE IF EXISTS interview_sessions;
