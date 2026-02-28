-- Migration 002: M0 job spec persistence
-- Up Strategy: Create normalized job spec storage and review history tables with optimistic-locking support.
-- Down Strategy: Drop job spec review artifacts first, then core job spec storage.

-- +goose Up
CREATE TABLE job_specs (
    job_spec_id TEXT PRIMARY KEY,
    ingestion_id TEXT REFERENCES job_ingestions (ingestion_id) ON DELETE SET NULL,
    source_type TEXT NOT NULL CHECK (source_type IN ('url', 'text', 'document_ref')),
    source_value TEXT NOT NULL,
    source_captured_at TIMESTAMP NOT NULL,
    company TEXT,
    role_title TEXT NOT NULL,
    seniority_level TEXT,
    location TEXT,
    employment_type TEXT,
    responsibilities_json TEXT NOT NULL,
    requirements_json TEXT NOT NULL,
    competency_weights_json TEXT NOT NULL,
    evidence_spans_json TEXT,
    extraction_confidence REAL NOT NULL CHECK (extraction_confidence BETWEEN 0 AND 1),
    taxonomy_version TEXT,
    version INTEGER NOT NULL DEFAULT 1 CHECK (version >= 1),
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_job_specs_ingestion_id ON job_specs (ingestion_id);
CREATE INDEX idx_job_specs_role_title ON job_specs (role_title);

CREATE TABLE job_spec_reviews (
    review_id TEXT PRIMARY KEY,
    job_spec_id TEXT NOT NULL REFERENCES job_specs (job_spec_id) ON DELETE CASCADE,
    expected_version INTEGER NOT NULL CHECK (expected_version >= 1),
    result_version INTEGER CHECK (result_version >= 1),
    patch_json TEXT NOT NULL,
    review_notes TEXT,
    reviewed_by TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_job_spec_reviews_job_spec_id ON job_spec_reviews (job_spec_id);
CREATE INDEX idx_job_spec_reviews_created_at ON job_spec_reviews (created_at);

-- +goose Down
DROP INDEX IF EXISTS idx_job_spec_reviews_created_at;
DROP INDEX IF EXISTS idx_job_spec_reviews_job_spec_id;
DROP TABLE IF EXISTS job_spec_reviews;

DROP INDEX IF EXISTS idx_job_specs_role_title;
DROP INDEX IF EXISTS idx_job_specs_ingestion_id;
DROP TABLE IF EXISTS job_specs;
