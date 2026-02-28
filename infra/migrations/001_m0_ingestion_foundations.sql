-- Migration 001: M0 ingestion foundations
-- Up Strategy: Create ingestion tables with idempotency and status constraints aligned to API contracts.
-- Down Strategy: Drop ingestion tables and indexes in reverse dependency order.

-- +goose Up
CREATE TABLE job_ingestions (
    ingestion_id TEXT PRIMARY KEY,
    idempotency_key TEXT NOT NULL UNIQUE,
    source_type TEXT NOT NULL CHECK (source_type IN ('url', 'text', 'document_ref')),
    source_value TEXT NOT NULL,
    target_locale TEXT NOT NULL DEFAULT 'en-US',
    status TEXT NOT NULL DEFAULT 'queued' CHECK (status IN ('queued', 'running', 'succeeded', 'failed', 'canceled')),
    current_stage TEXT NOT NULL DEFAULT 'queued',
    progress_pct INTEGER CHECK (progress_pct BETWEEN 0 AND 100),
    result_job_spec_id TEXT,
    error_code TEXT,
    error_message TEXT,
    error_retryable INTEGER CHECK (error_retryable IN (0, 1)),
    error_details_json TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    started_at TIMESTAMP,
    completed_at TIMESTAMP
);

CREATE INDEX idx_job_ingestions_status ON job_ingestions (status);
CREATE INDEX idx_job_ingestions_created_at ON job_ingestions (created_at);

CREATE TABLE candidate_ingestions (
    ingestion_id TEXT PRIMARY KEY,
    idempotency_key TEXT NOT NULL UNIQUE,
    candidate_id TEXT,
    cv_text TEXT,
    cv_document_ref TEXT,
    story_notes_json TEXT,
    target_roles_json TEXT,
    target_locale TEXT NOT NULL DEFAULT 'en-US',
    status TEXT NOT NULL DEFAULT 'queued' CHECK (status IN ('queued', 'running', 'succeeded', 'failed', 'canceled')),
    current_stage TEXT NOT NULL DEFAULT 'queued',
    progress_pct INTEGER CHECK (progress_pct BETWEEN 0 AND 100),
    result_candidate_id TEXT,
    error_code TEXT,
    error_message TEXT,
    error_retryable INTEGER CHECK (error_retryable IN (0, 1)),
    error_details_json TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    CHECK ((cv_text IS NOT NULL) <> (cv_document_ref IS NOT NULL))
);

CREATE INDEX idx_candidate_ingestions_status ON candidate_ingestions (status);
CREATE INDEX idx_candidate_ingestions_created_at ON candidate_ingestions (created_at);

-- +goose Down
DROP INDEX IF EXISTS idx_candidate_ingestions_created_at;
DROP INDEX IF EXISTS idx_candidate_ingestions_status;
DROP TABLE IF EXISTS candidate_ingestions;

DROP INDEX IF EXISTS idx_job_ingestions_created_at;
DROP INDEX IF EXISTS idx_job_ingestions_status;
DROP TABLE IF EXISTS job_ingestions;
