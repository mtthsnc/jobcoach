-- Migration 010: M6 negotiation plan endpoint foundation
-- Up Strategy: Create negotiation plan persistence table with idempotency semantics.
-- Down Strategy: Drop negotiation plan table and indexes.

-- +goose Up
CREATE TABLE negotiation_plans (
    negotiation_plan_id TEXT PRIMARY KEY,
    candidate_id TEXT NOT NULL REFERENCES candidate_profiles (candidate_id) ON DELETE CASCADE,
    target_role TEXT NOT NULL,
    idempotency_key TEXT NOT NULL UNIQUE,
    request_json TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_negotiation_plans_candidate_id ON negotiation_plans (candidate_id);
CREATE INDEX idx_negotiation_plans_target_role ON negotiation_plans (target_role);

-- +goose Down
DROP INDEX IF EXISTS idx_negotiation_plans_target_role;
DROP INDEX IF EXISTS idx_negotiation_plans_candidate_id;
DROP TABLE IF EXISTS negotiation_plans;
