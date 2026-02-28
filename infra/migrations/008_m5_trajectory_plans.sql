-- Migration 008: M5 trajectory plan endpoint foundation
-- Up Strategy: Create trajectory plan persistence table with idempotency semantics.
-- Down Strategy: Drop trajectory plan table and indexes.

-- +goose Up
CREATE TABLE trajectory_plans (
    trajectory_plan_id TEXT PRIMARY KEY,
    candidate_id TEXT NOT NULL REFERENCES candidate_profiles (candidate_id) ON DELETE CASCADE,
    target_role TEXT NOT NULL,
    idempotency_key TEXT NOT NULL UNIQUE,
    request_json TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_trajectory_plans_candidate_id ON trajectory_plans (candidate_id);
CREATE INDEX idx_trajectory_plans_target_role ON trajectory_plans (target_role);

-- +goose Down
DROP INDEX IF EXISTS idx_trajectory_plans_target_role;
DROP INDEX IF EXISTS idx_trajectory_plans_candidate_id;
DROP TABLE IF EXISTS trajectory_plans;
