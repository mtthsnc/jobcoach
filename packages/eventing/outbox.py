from __future__ import annotations

import json
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Protocol

from packages.db.sqlite import connect_row_factory


@dataclass(frozen=True)
class OutboxEvent:
    event_id: str
    aggregate_type: str
    aggregate_id: str
    event_type: str
    payload: Mapping[str, Any]
    available_at: datetime


class OutboxStore(Protocol):
    def enqueue(self, event: OutboxEvent) -> None:
        """Persist a new outbox event in pending state."""

    def dequeue_ready(self, limit: int = 100, now: datetime | None = None) -> list[OutboxEvent]:
        """Fetch pending events that are ready to publish."""

    def mark_published(self, event_id: str, published_at: datetime | None = None) -> bool:
        """Transition a pending event to published."""


class SQLiteOutboxStore:
    """SQLite-backed outbox store for the `outbox_events` table."""

    def __init__(self, db_path: str | Path) -> None:
        self._db_path = str(db_path)

    def enqueue(self, event: OutboxEvent) -> None:
        with closing(self._connect()) as connection:
            with connection:
                connection.execute(
                    """
                    INSERT INTO outbox_events (
                        event_id,
                        aggregate_type,
                        aggregate_id,
                        event_type,
                        payload_json,
                        available_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        event.event_id,
                        event.aggregate_type,
                        event.aggregate_id,
                        event.event_type,
                        json.dumps(event.payload, separators=(",", ":")),
                        _to_sqlite_timestamp(event.available_at),
                    ),
                )

    def dequeue_ready(self, limit: int = 100, now: datetime | None = None) -> list[OutboxEvent]:
        effective_now = now or datetime.now(timezone.utc)
        with closing(self._connect()) as connection:
            rows = connection.execute(
                """
                SELECT
                    event_id,
                    aggregate_type,
                    aggregate_id,
                    event_type,
                    payload_json,
                    available_at
                FROM outbox_events
                WHERE status = 'pending'
                  AND available_at <= ?
                ORDER BY available_at ASC, created_at ASC
                LIMIT ?
                """,
                (_to_sqlite_timestamp(effective_now), limit),
            ).fetchall()

        return [
            OutboxEvent(
                event_id=row["event_id"],
                aggregate_type=row["aggregate_type"],
                aggregate_id=row["aggregate_id"],
                event_type=row["event_type"],
                payload=json.loads(row["payload_json"]),
                available_at=_from_sqlite_timestamp(row["available_at"]),
            )
            for row in rows
        ]

    def mark_published(self, event_id: str, published_at: datetime | None = None) -> bool:
        effective_published_at = published_at or datetime.now(timezone.utc)
        with closing(self._connect()) as connection:
            with connection:
                cursor = connection.execute(
                    """
                    UPDATE outbox_events
                    SET status = 'published',
                        published_at = ?
                    WHERE event_id = ?
                      AND status = 'pending'
                    """,
                    (_to_sqlite_timestamp(effective_published_at), event_id),
                )
                return cursor.rowcount == 1

    def _connect(self):
        return connect_row_factory(self._db_path)


def _to_sqlite_timestamp(value: datetime) -> str:
    normalized = value.astimezone(timezone.utc).replace(tzinfo=None) if value.tzinfo else value
    return normalized.isoformat(sep=" ", timespec="seconds")


def _from_sqlite_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace(" ", "T")).replace(tzinfo=timezone.utc)
