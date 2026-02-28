-- Migration 006: M4 feedback report endpoint foundation
-- Up Strategy: Create feedback report persistence table with idempotency semantics.
-- Down Strategy: Drop feedback report table and indexes.

-- +goose Up
CREATE TABLE feedback_reports (
    feedback_report_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES interview_sessions (session_id) ON DELETE CASCADE,
    idempotency_key TEXT NOT NULL UNIQUE,
    request_json TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_feedback_reports_session_id ON feedback_reports (session_id);

-- +goose Down
DROP INDEX IF EXISTS idx_feedback_reports_session_id;
DROP TABLE IF EXISTS feedback_reports;
