-- Migration 003: M0 candidate profile persistence
-- Up Strategy: Create candidate profile and storybank tables matching candidate profile/story retrieval contracts.
-- Down Strategy: Drop storybank data first, then candidate profile records.

-- +goose Up
CREATE TABLE candidate_profiles (
    candidate_id TEXT PRIMARY KEY,
    ingestion_id TEXT REFERENCES candidate_ingestions (ingestion_id) ON DELETE SET NULL,
    summary TEXT NOT NULL,
    target_roles_json TEXT,
    experience_json TEXT NOT NULL,
    skills_json TEXT NOT NULL,
    parse_confidence REAL NOT NULL CHECK (parse_confidence BETWEEN 0 AND 1),
    version INTEGER NOT NULL DEFAULT 1 CHECK (version >= 1),
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_candidate_profiles_ingestion_id ON candidate_profiles (ingestion_id);

CREATE TABLE candidate_storybank (
    story_id TEXT PRIMARY KEY,
    candidate_id TEXT NOT NULL REFERENCES candidate_profiles (candidate_id) ON DELETE CASCADE,
    situation TEXT NOT NULL,
    task TEXT NOT NULL,
    action TEXT NOT NULL,
    result TEXT NOT NULL,
    competencies_json TEXT NOT NULL,
    metrics_json TEXT,
    evidence_quality REAL NOT NULL CHECK (evidence_quality BETWEEN 0 AND 1),
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_candidate_storybank_candidate_id ON candidate_storybank (candidate_id);
CREATE INDEX idx_candidate_storybank_evidence_quality ON candidate_storybank (evidence_quality);

-- +goose Down
DROP INDEX IF EXISTS idx_candidate_storybank_evidence_quality;
DROP INDEX IF EXISTS idx_candidate_storybank_candidate_id;
DROP TABLE IF EXISTS candidate_storybank;

DROP INDEX IF EXISTS idx_candidate_profiles_ingestion_id;
DROP TABLE IF EXISTS candidate_profiles;
