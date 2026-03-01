-- Migration 011: M6 negotiation plan versioning hardening
-- Up Strategy: Add negotiation plan version metadata and per-candidate/role version uniqueness.
-- Down Strategy: Remove version metadata columns and related indexes.

-- +goose Up
ALTER TABLE negotiation_plans ADD COLUMN version INTEGER NOT NULL DEFAULT 1;
ALTER TABLE negotiation_plans ADD COLUMN supersedes_negotiation_plan_id TEXT REFERENCES negotiation_plans (negotiation_plan_id);

WITH ranked AS (
    SELECT
        negotiation_plan_id,
        ROW_NUMBER() OVER (
            PARTITION BY candidate_id, target_role
            ORDER BY created_at ASC, negotiation_plan_id ASC
        ) AS ranked_version,
        LAG(negotiation_plan_id) OVER (
            PARTITION BY candidate_id, target_role
            ORDER BY created_at ASC, negotiation_plan_id ASC
        ) AS ranked_supersedes
    FROM negotiation_plans
)
UPDATE negotiation_plans
SET
    version = COALESCE(
        (
            SELECT ranked_version
            FROM ranked
            WHERE ranked.negotiation_plan_id = negotiation_plans.negotiation_plan_id
        ),
        1
    ),
    supersedes_negotiation_plan_id = (
        SELECT ranked_supersedes
        FROM ranked
        WHERE ranked.negotiation_plan_id = negotiation_plans.negotiation_plan_id
    );

CREATE UNIQUE INDEX idx_negotiation_plans_candidate_role_version
    ON negotiation_plans (candidate_id, target_role, version);
CREATE INDEX idx_negotiation_plans_candidate_role_latest
    ON negotiation_plans (candidate_id, target_role, version DESC, created_at DESC);

-- +goose Down
DROP INDEX IF EXISTS idx_negotiation_plans_candidate_role_latest;
DROP INDEX IF EXISTS idx_negotiation_plans_candidate_role_version;

ALTER TABLE negotiation_plans DROP COLUMN supersedes_negotiation_plan_id;
ALTER TABLE negotiation_plans DROP COLUMN version;
