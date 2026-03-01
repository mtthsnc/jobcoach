from __future__ import annotations

import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

from packages.eventing.outbox import (
    OutboxEvent,
    OutboxEventPublisher,
    OutboxRelayPolicy,
    OutboxRelayWorker,
    SQLiteOutboxStore,
)


class _DeterministicPublisher(OutboxEventPublisher):
    def __init__(self, *, failures_by_event_id: dict[str, int] | None = None, always_fail: bool = False) -> None:
        self._failures_by_event_id = dict(failures_by_event_id or {})
        self._always_fail = always_fail
        self.published_event_ids: list[str] = []

    def publish(self, event: OutboxEvent) -> None:
        self.published_event_ids.append(event.event_id)
        if self._always_fail:
            raise RuntimeError("simulated relay delivery failure")

        remaining_failures = self._failures_by_event_id.get(event.event_id, 0)
        if remaining_failures > 0:
            self._failures_by_event_id[event.event_id] = remaining_failures - 1
            raise RuntimeError("simulated relay delivery failure")


class OutboxRelayWorkerTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tempdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tempdir.name) / "relay.sqlite3"
        self._create_schema(self.db_path)
        self.store = SQLiteOutboxStore(self.db_path)

    def tearDown(self) -> None:
        self._tempdir.cleanup()

    def test_run_once_publishes_ready_event(self) -> None:
        self.store.enqueue(
            OutboxEvent(
                event_id="evt-001",
                aggregate_type="eval_run",
                aggregate_id="eval-001",
                event_type="eval_run.queued",
                payload={"eval_run_id": "eval-001", "status": "queued"},
                available_at=datetime(2026, 2, 2, 10, 0, tzinfo=UTC),
            )
        )
        publisher = _DeterministicPublisher()
        worker = OutboxRelayWorker(store=self.store, publisher=publisher, policy=OutboxRelayPolicy(max_attempts=3))

        result = worker.run_once(limit=10, now=datetime(2026, 2, 2, 10, 0, tzinfo=UTC))

        self.assertEqual(result.dequeued_count, 1)
        self.assertEqual(result.published_count, 1)
        self.assertEqual(result.retry_scheduled_count, 0)
        self.assertEqual(result.dead_lettered_count, 0)
        self.assertEqual(result.skipped_count, 0)
        self.assertEqual(publisher.published_event_ids, ["evt-001"])
        row = self._load_event_row("evt-001")
        self.assertEqual(row["status"], "published")
        self.assertEqual(row["publish_attempts"], 0)
        self.assertEqual(row["failure_count"], 0)
        self.assertEqual(row["published_at"], "2026-02-02 10:00:00")
        self.assertIsNone(row["last_error"])

    def test_run_once_schedules_retry_then_succeeds(self) -> None:
        self.store.enqueue(
            OutboxEvent(
                event_id="evt-002",
                aggregate_type="eval_run",
                aggregate_id="eval-002",
                event_type="eval_run.queued",
                payload={"eval_run_id": "eval-002", "status": "queued"},
                available_at=datetime(2026, 2, 2, 11, 0, tzinfo=UTC),
            )
        )
        publisher = _DeterministicPublisher(failures_by_event_id={"evt-002": 1})
        policy = OutboxRelayPolicy(max_attempts=3, retry_delays_seconds=(30, 90))
        worker = OutboxRelayWorker(store=self.store, publisher=publisher, policy=policy)

        first = worker.run_once(limit=10, now=datetime(2026, 2, 2, 11, 0, tzinfo=UTC))
        self.assertEqual(first.published_count, 0)
        self.assertEqual(first.retry_scheduled_count, 1)
        retry_row = self._load_event_row("evt-002")
        self.assertEqual(retry_row["status"], "pending")
        self.assertEqual(retry_row["publish_attempts"], 1)
        self.assertEqual(retry_row["failure_count"], 1)
        self.assertEqual(retry_row["available_at"], "2026-02-02 11:00:30")
        self.assertEqual(retry_row["last_error"], "RuntimeError: simulated relay delivery failure")

        too_early = worker.run_once(limit=10, now=datetime(2026, 2, 2, 11, 0, 29, tzinfo=UTC))
        self.assertEqual(too_early.dequeued_count, 0)
        self.assertEqual(too_early.published_count, 0)

        second = worker.run_once(limit=10, now=datetime(2026, 2, 2, 11, 0, 30, tzinfo=UTC))
        self.assertEqual(second.dequeued_count, 1)
        self.assertEqual(second.published_count, 1)
        self.assertEqual(second.retry_scheduled_count, 0)
        published_row = self._load_event_row("evt-002")
        self.assertEqual(published_row["status"], "published")
        self.assertEqual(published_row["publish_attempts"], 1)
        self.assertEqual(published_row["failure_count"], 1)
        self.assertEqual(published_row["published_at"], "2026-02-02 11:00:30")
        self.assertIsNone(published_row["last_error"])

    def test_run_once_dead_letters_after_retry_exhaustion(self) -> None:
        self.store.enqueue(
            OutboxEvent(
                event_id="evt-003",
                aggregate_type="eval_run",
                aggregate_id="eval-003",
                event_type="eval_run.failed",
                payload={"eval_run_id": "eval-003", "status": "failed"},
                available_at=datetime(2026, 2, 2, 12, 0, tzinfo=UTC),
            )
        )
        publisher = _DeterministicPublisher(always_fail=True)
        policy = OutboxRelayPolicy(max_attempts=2, retry_delays_seconds=(20,))
        worker = OutboxRelayWorker(store=self.store, publisher=publisher, policy=policy)

        first = worker.run_once(limit=10, now=datetime(2026, 2, 2, 12, 0, tzinfo=UTC))
        self.assertEqual(first.retry_scheduled_count, 1)
        self.assertEqual(first.dead_lettered_count, 0)

        second = worker.run_once(limit=10, now=datetime(2026, 2, 2, 12, 0, 20, tzinfo=UTC))
        self.assertEqual(second.retry_scheduled_count, 0)
        self.assertEqual(second.dead_lettered_count, 1)
        dead_letter_row = self._load_event_row("evt-003")
        self.assertEqual(dead_letter_row["status"], "failed")
        self.assertEqual(dead_letter_row["publish_attempts"], 2)
        self.assertEqual(dead_letter_row["failure_count"], 2)
        self.assertEqual(
            dead_letter_row["last_error"],
            "dead_letter:RuntimeError: simulated relay delivery failure",
        )
        self.assertEqual(dead_letter_row["dead_lettered_at"], "2026-02-02 12:00:20")

        replay = worker.run_once(limit=10, now=datetime(2026, 2, 2, 12, 1, tzinfo=UTC))
        self.assertEqual(replay.dequeued_count, 0)
        self.assertEqual(replay.published_count, 0)

    def _load_event_row(self, event_id: str) -> sqlite3.Row:
        with closing(sqlite3.connect(self.db_path)) as connection:
            connection.row_factory = sqlite3.Row
            row = connection.execute(
                """
                SELECT
                    event_id,
                    status,
                    publish_attempts,
                    failure_count,
                    available_at,
                    published_at,
                    last_error,
                    dead_lettered_at
                FROM outbox_events
                WHERE event_id = ?
                """,
                (event_id,),
            ).fetchone()
        self.assertIsNotNone(row)
        assert row is not None
        return row

    @staticmethod
    def _create_schema(db_path: Path) -> None:
        with closing(sqlite3.connect(db_path)) as connection:
            connection.executescript(
                """
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
                    publish_attempts INTEGER NOT NULL DEFAULT 0 CHECK (publish_attempts >= 0),
                    last_error TEXT,
                    dead_lettered_at TIMESTAMP,
                    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX idx_outbox_events_status_available_at ON outbox_events (status, available_at);
                CREATE INDEX idx_outbox_events_aggregate ON outbox_events (aggregate_type, aggregate_id);
                """
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
