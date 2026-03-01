-- Migration 012: M7 eval run suite catalog expansion and idempotency storage
-- Up Strategy: Rebuild eval_runs with expanded suite catalog and idempotency request persistence columns.
-- Down Strategy: Rebuild eval_runs back to the original M0 shape and suite subset.

-- +goose Up
CREATE TABLE eval_runs_m7_new (
    eval_run_id TEXT PRIMARY KEY,
    suite TEXT NOT NULL CHECK (
        suite IN (
            'job_extraction_v1',
            'candidate_parse_v1',
            'interview_relevance_v1',
            'feedback_quality_v1',
            'trajectory_quality_v1',
            'negotiation_quality_v1'
        )
    ),
    status TEXT NOT NULL DEFAULT 'queued' CHECK (status IN ('queued', 'running', 'succeeded', 'failed')),
    metrics_json TEXT,
    error_code TEXT,
    error_message TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    idempotency_key TEXT,
    request_json TEXT
);

INSERT INTO eval_runs_m7_new (
    eval_run_id,
    suite,
    status,
    metrics_json,
    error_code,
    error_message,
    created_at,
    started_at,
    completed_at,
    idempotency_key,
    request_json
)
SELECT
    eval_run_id,
    suite,
    status,
    metrics_json,
    error_code,
    error_message,
    created_at,
    started_at,
    completed_at,
    NULL,
    NULL
FROM eval_runs;

DROP TABLE eval_runs;
ALTER TABLE eval_runs_m7_new RENAME TO eval_runs;

CREATE INDEX idx_eval_runs_status ON eval_runs (status);
CREATE INDEX idx_eval_runs_suite ON eval_runs (suite);
CREATE UNIQUE INDEX idx_eval_runs_idempotency_key
    ON eval_runs (idempotency_key)
    WHERE idempotency_key IS NOT NULL;

-- +goose Down
CREATE TABLE eval_runs_m7_old (
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

INSERT INTO eval_runs_m7_old (
    eval_run_id,
    suite,
    status,
    metrics_json,
    error_code,
    error_message,
    created_at,
    started_at,
    completed_at
)
SELECT
    eval_run_id,
    suite,
    status,
    metrics_json,
    error_code,
    error_message,
    created_at,
    started_at,
    completed_at
FROM eval_runs
WHERE suite IN ('job_extraction_v1', 'candidate_parse_v1');

DROP TABLE eval_runs;
ALTER TABLE eval_runs_m7_old RENAME TO eval_runs;

CREATE INDEX idx_eval_runs_status ON eval_runs (status);
CREATE INDEX idx_eval_runs_suite ON eval_runs (suite);
