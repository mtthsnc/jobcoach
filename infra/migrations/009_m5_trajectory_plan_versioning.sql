-- Migration 009: M5 trajectory plan versioning hardening
-- Up Strategy: Add trajectory plan version metadata and per-candidate/role version uniqueness.
-- Down Strategy: Remove version metadata columns and related indexes.

-- +goose Up
ALTER TABLE trajectory_plans ADD COLUMN version INTEGER NOT NULL DEFAULT 1;
ALTER TABLE trajectory_plans ADD COLUMN supersedes_trajectory_plan_id TEXT REFERENCES trajectory_plans (trajectory_plan_id);

WITH ranked AS (
    SELECT
        trajectory_plan_id,
        ROW_NUMBER() OVER (
            PARTITION BY candidate_id, target_role
            ORDER BY created_at ASC, trajectory_plan_id ASC
        ) AS ranked_version,
        LAG(trajectory_plan_id) OVER (
            PARTITION BY candidate_id, target_role
            ORDER BY created_at ASC, trajectory_plan_id ASC
        ) AS ranked_supersedes
    FROM trajectory_plans
)
UPDATE trajectory_plans
SET
    version = COALESCE(
        (
            SELECT ranked_version
            FROM ranked
            WHERE ranked.trajectory_plan_id = trajectory_plans.trajectory_plan_id
        ),
        1
    ),
    supersedes_trajectory_plan_id = (
        SELECT ranked_supersedes
        FROM ranked
        WHERE ranked.trajectory_plan_id = trajectory_plans.trajectory_plan_id
    );

CREATE UNIQUE INDEX idx_trajectory_plans_candidate_role_version
    ON trajectory_plans (candidate_id, target_role, version);
CREATE INDEX idx_trajectory_plans_candidate_role_latest
    ON trajectory_plans (candidate_id, target_role, version DESC, created_at DESC);

-- +goose Down
DROP INDEX IF EXISTS idx_trajectory_plans_candidate_role_latest;
DROP INDEX IF EXISTS idx_trajectory_plans_candidate_role_version;

ALTER TABLE trajectory_plans DROP COLUMN supersedes_trajectory_plan_id;
ALTER TABLE trajectory_plans DROP COLUMN version;
