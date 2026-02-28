-- Migration 004: M0 taxonomy, eval, and outbox foundations
-- Up Strategy: Create taxonomy mapping, eval run tracking, and event outbox tables for M0 workflow orchestration.
-- Down Strategy: Drop outbox and eval/taxonomy support tables in reverse creation order.

-- +goose Up
CREATE TABLE taxonomy_mappings (
    mapping_id TEXT PRIMARY KEY,
    taxonomy_version TEXT NOT NULL,
    input_term TEXT NOT NULL,
    canonical_term TEXT NOT NULL,
    confidence REAL CHECK (confidence BETWEEN 0 AND 1),
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (taxonomy_version, input_term)
);

CREATE INDEX idx_taxonomy_mappings_canonical_term ON taxonomy_mappings (canonical_term);

CREATE TABLE eval_runs (
    eval_run_id TEXT PRIMARY KEY,
    suite TEXT NOT NULL CHECK (suite IN ('job_extraction_v1', 'candidate_parse_v1')),
    status TEXT NOT NULL DEFAULT 'queued' CHECK (status IN ('queued', 'running', 'succeeded', 'failed')),
    metrics_json TEXT,
    error_code TEXT,
    error_message TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    started_at TIMESTAMP,
    completed_at TIMESTAMP
);

CREATE INDEX idx_eval_runs_status ON eval_runs (status);
CREATE INDEX idx_eval_runs_suite ON eval_runs (suite);

CREATE TABLE outbox_events (
    event_id TEXT PRIMARY KEY,
    aggregate_type TEXT NOT NULL,
    aggregate_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'published', 'failed')),
    available_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    published_at TIMESTAMP,
    failure_count INTEGER NOT NULL DEFAULT 0 CHECK (failure_count >= 0),
    last_error TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_outbox_events_status_available_at ON outbox_events (status, available_at);
CREATE INDEX idx_outbox_events_aggregate ON outbox_events (aggregate_type, aggregate_id);

-- +goose Down
DROP INDEX IF EXISTS idx_outbox_events_aggregate;
DROP INDEX IF EXISTS idx_outbox_events_status_available_at;
DROP TABLE IF EXISTS outbox_events;

DROP INDEX IF EXISTS idx_eval_runs_suite;
DROP INDEX IF EXISTS idx_eval_runs_status;
DROP TABLE IF EXISTS eval_runs;

DROP INDEX IF EXISTS idx_taxonomy_mappings_canonical_term;
DROP TABLE IF EXISTS taxonomy_mappings;
