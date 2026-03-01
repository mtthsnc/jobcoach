from __future__ import annotations

import json
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol

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

    def record_publish_failure(
        self,
        event_id: str,
        *,
        error_message: str,
        max_attempts: int,
        retry_delay_for_attempt: Callable[[int], int],
        now: datetime | None = None,
    ) -> "OutboxFailureTransition | None":
        """Record publish failure, schedule retry, or move event to dead-letter state."""


class OutboxEventPublisher(Protocol):
    def publish(self, event: OutboxEvent) -> None:
        """Publish an outbox event to downstream transport."""


@dataclass(frozen=True)
class OutboxFailureTransition:
    event_id: str
    status: str
    publish_attempts: int
    next_available_at: datetime | None
    last_error: str
    dead_lettered_at: datetime | None


@dataclass(frozen=True)
class OutboxRelayPolicy:
    max_attempts: int = 5
    retry_delays_seconds: tuple[int, ...] = (5, 15, 30, 60, 120)

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be >= 1")
        if not self.retry_delays_seconds:
            raise ValueError("retry_delays_seconds must be non-empty")
        for delay in self.retry_delays_seconds:
            if delay < 0:
                raise ValueError("retry_delays_seconds values must be >= 0")

    def delay_for_attempt(self, attempt: int) -> int:
        if attempt < 1:
            raise ValueError("attempt must be >= 1")
        index = min(attempt - 1, len(self.retry_delays_seconds) - 1)
        return self.retry_delays_seconds[index]


@dataclass(frozen=True)
class OutboxRelayRunResult:
    dequeued_count: int
    published_count: int
    retry_scheduled_count: int
    dead_lettered_count: int
    skipped_count: int


class OutboxRelayWorker:
    """Relay worker that publishes ready outbox events with bounded retries."""

    def __init__(
        self,
        *,
        store: OutboxStore,
        publisher: OutboxEventPublisher,
        policy: OutboxRelayPolicy | None = None,
    ) -> None:
        self._store = store
        self._publisher = publisher
        self._policy = policy or OutboxRelayPolicy()

    def run_once(self, *, limit: int = 100, now: datetime | None = None) -> OutboxRelayRunResult:
        effective_now = now or datetime.now(timezone.utc)
        ready_events = self._store.dequeue_ready(limit=limit, now=effective_now)
        published_count = 0
        retry_scheduled_count = 0
        dead_lettered_count = 0
        skipped_count = 0

        for event in ready_events:
            try:
                self._publisher.publish(event)
            except Exception as exc:  # noqa: BLE001 - relay worker handles downstream failures explicitly.
                transition = self._store.record_publish_failure(
                    event.event_id,
                    error_message=_format_publish_error(exc),
                    max_attempts=self._policy.max_attempts,
                    retry_delay_for_attempt=self._policy.delay_for_attempt,
                    now=effective_now,
                )
                if transition is None:
                    skipped_count += 1
                elif transition.status == "failed":
                    dead_lettered_count += 1
                else:
                    retry_scheduled_count += 1
                continue

            if self._store.mark_published(event.event_id, published_at=effective_now):
                published_count += 1
            else:
                skipped_count += 1

        return OutboxRelayRunResult(
            dequeued_count=len(ready_events),
            published_count=published_count,
            retry_scheduled_count=retry_scheduled_count,
            dead_lettered_count=dead_lettered_count,
            skipped_count=skipped_count,
        )


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
                        published_at = ?,
                        last_error = NULL
                    WHERE event_id = ?
                      AND status = 'pending'
                    """,
                    (_to_sqlite_timestamp(effective_published_at), event_id),
                )
                return cursor.rowcount == 1

    def record_publish_failure(
        self,
        event_id: str,
        *,
        error_message: str,
        max_attempts: int,
        retry_delay_for_attempt: Callable[[int], int],
        now: datetime | None = None,
    ) -> OutboxFailureTransition | None:
        if max_attempts < 1:
            raise ValueError("max_attempts must be >= 1")
        effective_now = now or datetime.now(timezone.utc)
        normalized_error = _normalize_error_message(error_message)

        with closing(self._connect()) as connection:
            with connection:
                row = connection.execute(
                    """
                    SELECT publish_attempts
                    FROM outbox_events
                    WHERE event_id = ?
                      AND status = 'pending'
                    """,
                    (event_id,),
                ).fetchone()
                if row is None:
                    return None

                publish_attempts = int(row["publish_attempts"]) + 1
                dead_lettered = publish_attempts >= max_attempts
                status = "failed" if dead_lettered else "pending"
                dead_lettered_at = effective_now if dead_lettered else None
                next_available_at = None
                if dead_lettered:
                    available_at = effective_now
                    last_error = f"dead_letter:{normalized_error}"
                else:
                    retry_delay_seconds = max(0, int(retry_delay_for_attempt(publish_attempts)))
                    next_available_at = effective_now + timedelta(seconds=retry_delay_seconds)
                    available_at = next_available_at
                    last_error = normalized_error

                cursor = connection.execute(
                    """
                    UPDATE outbox_events
                    SET status = ?,
                        publish_attempts = ?,
                        failure_count = ?,
                        available_at = ?,
                        last_error = ?,
                        dead_lettered_at = COALESCE(?, dead_lettered_at)
                    WHERE event_id = ?
                      AND status = 'pending'
                    """,
                    (
                        status,
                        publish_attempts,
                        publish_attempts,
                        _to_sqlite_timestamp(available_at),
                        last_error,
                        _to_sqlite_timestamp(dead_lettered_at) if dead_lettered_at is not None else None,
                        event_id,
                    ),
                )
                if cursor.rowcount != 1:
                    return None

                return OutboxFailureTransition(
                    event_id=event_id,
                    status=status,
                    publish_attempts=publish_attempts,
                    next_available_at=next_available_at,
                    last_error=last_error,
                    dead_lettered_at=dead_lettered_at,
                )

    def _connect(self):
        return connect_row_factory(self._db_path)


def _to_sqlite_timestamp(value: datetime) -> str:
    normalized = value.astimezone(timezone.utc).replace(tzinfo=None) if value.tzinfo else value
    return normalized.isoformat(sep=" ", timespec="seconds")


def _from_sqlite_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace(" ", "T")).replace(tzinfo=timezone.utc)


def _normalize_error_message(raw_error: str, *, max_length: int = 512) -> str:
    compact = " ".join(str(raw_error).strip().split())
    if not compact:
        compact = "publish_error"
    return compact[:max_length]


def _format_publish_error(error: Exception) -> str:
    message = str(error).strip()
    if not message:
        return error.__class__.__name__
    return f"{error.__class__.__name__}: {message}"
