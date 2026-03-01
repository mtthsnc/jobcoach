-- Migration 013: M8 outbox relay reliability metadata
-- Up Strategy: Add publish-attempt and dead-letter metadata columns required by relay worker transitions.
-- Down Strategy: Rebuild outbox_events schema without M8 relay metadata columns.

-- +goose Up
ALTER TABLE outbox_events
ADD COLUMN publish_attempts INTEGER NOT NULL DEFAULT 0 CHECK (publish_attempts >= 0);

UPDATE outbox_events
SET publish_attempts = failure_count
WHERE failure_count > publish_attempts;

ALTER TABLE outbox_events
ADD COLUMN dead_lettered_at TIMESTAMP;

-- +goose Down
DROP INDEX IF EXISTS idx_outbox_events_status_available_at;
DROP INDEX IF EXISTS idx_outbox_events_aggregate;

ALTER TABLE outbox_events RENAME TO outbox_events_m8_003;

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

INSERT INTO outbox_events (
    event_id,
    aggregate_type,
    aggregate_id,
    event_type,
    payload_json,
    status,
    available_at,
    published_at,
    failure_count,
    last_error,
    created_at
)
SELECT
    event_id,
    aggregate_type,
    aggregate_id,
    event_type,
    payload_json,
    status,
    available_at,
    published_at,
    CASE
        WHEN publish_attempts > failure_count THEN publish_attempts
        ELSE failure_count
    END AS failure_count,
    last_error,
    created_at
FROM outbox_events_m8_003;

DROP TABLE outbox_events_m8_003;

CREATE INDEX idx_outbox_events_status_available_at ON outbox_events (status, available_at);
CREATE INDEX idx_outbox_events_aggregate ON outbox_events (aggregate_type, aggregate_id);
