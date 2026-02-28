-- Migration 007: M4 feedback report versioning hardening
-- Up Strategy: Add feedback report versioning metadata and per-session version uniqueness.
-- Down Strategy: Remove versioning metadata columns and related indexes.

-- +goose Up
ALTER TABLE feedback_reports ADD COLUMN version INTEGER NOT NULL DEFAULT 1;
ALTER TABLE feedback_reports ADD COLUMN supersedes_feedback_report_id TEXT REFERENCES feedback_reports (feedback_report_id);

CREATE UNIQUE INDEX idx_feedback_reports_session_version ON feedback_reports (session_id, version);
CREATE INDEX idx_feedback_reports_session_latest ON feedback_reports (session_id, created_at DESC);

-- +goose Down
DROP INDEX IF EXISTS idx_feedback_reports_session_latest;
DROP INDEX IF EXISTS idx_feedback_reports_session_version;

ALTER TABLE feedback_reports DROP COLUMN supersedes_feedback_report_id;
ALTER TABLE feedback_reports DROP COLUMN version;
