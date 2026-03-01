from __future__ import annotations

import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path

from packages.eventing.outbox import OutboxEvent, SQLiteOutboxStore


class SQLiteOutboxStoreTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tempdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tempdir.name) / "outbox.sqlite3"
        self._create_schema(self.db_path)
        self.store = SQLiteOutboxStore(self.db_path)

    def tearDown(self) -> None:
        self._tempdir.cleanup()

    def test_enqueue_dequeue_mark_published_flow(self) -> None:
        event = OutboxEvent(
            event_id="evt-001",
            aggregate_type="job_ingestion",
            aggregate_id="ing-123",
            event_type="job.ingestion.created",
            payload={"job_ingestion_id": "ing-123"},
            available_at=datetime(2026, 2, 1, 10, 0, tzinfo=UTC),
        )
        self.store.enqueue(event)

        dequeued = self.store.dequeue_ready(limit=10, now=datetime(2026, 2, 1, 11, 0, tzinfo=UTC))
        self.assertEqual(len(dequeued), 1)
        self.assertEqual(dequeued[0], event)

        was_marked = self.store.mark_published(event.event_id, published_at=datetime(2026, 2, 1, 12, 0, tzinfo=UTC))
        self.assertTrue(was_marked)

        dequeued_after_publish = self.store.dequeue_ready(limit=10, now=datetime(2026, 2, 1, 13, 0, tzinfo=UTC))
        self.assertEqual(dequeued_after_publish, [])

        with closing(sqlite3.connect(self.db_path)) as connection:
            status, published_at = connection.execute(
                "SELECT status, published_at FROM outbox_events WHERE event_id = ?",
                (event.event_id,),
            ).fetchone()
        self.assertEqual(status, "published")
        self.assertEqual(published_at, "2026-02-01 12:00:00")

    def test_dequeue_only_returns_ready_events(self) -> None:
        self.store.enqueue(
            OutboxEvent(
                event_id="evt-002",
                aggregate_type="job_ingestion",
                aggregate_id="ing-456",
                event_type="job.ingestion.created",
                payload={"job_ingestion_id": "ing-456"},
                available_at=datetime(2026, 2, 1, 15, 0, tzinfo=UTC),
            )
        )

        not_ready = self.store.dequeue_ready(limit=10, now=datetime(2026, 2, 1, 14, 59, tzinfo=UTC))
        self.assertEqual(not_ready, [])

        ready = self.store.dequeue_ready(limit=10, now=datetime(2026, 2, 1, 15, 0, tzinfo=UTC))
        self.assertEqual(len(ready), 1)
        self.assertEqual(ready[0].event_id, "evt-002")

    def test_record_publish_failure_schedules_retry_then_dead_letters(self) -> None:
        event = OutboxEvent(
            event_id="evt-003",
            aggregate_type="eval_run",
            aggregate_id="eval-003",
            event_type="eval_run.queued",
            payload={"eval_run_id": "eval-003", "status": "queued"},
            available_at=datetime(2026, 2, 1, 10, 0, tzinfo=UTC),
        )
        self.store.enqueue(event)

        first_transition = self.store.record_publish_failure(
            event.event_id,
            error_message="RuntimeError: broker timeout",
            max_attempts=2,
            retry_delay_for_attempt=lambda _: 45,
            now=datetime(2026, 2, 1, 10, 5, tzinfo=UTC),
        )
        self.assertIsNotNone(first_transition)
        assert first_transition is not None
        self.assertEqual(first_transition.status, "pending")
        self.assertEqual(first_transition.publish_attempts, 1)
        self.assertEqual(first_transition.next_available_at, datetime(2026, 2, 1, 10, 5, tzinfo=UTC) + timedelta(seconds=45))
        self.assertEqual(first_transition.last_error, "RuntimeError: broker timeout")
        self.assertIsNone(first_transition.dead_lettered_at)

        second_transition = self.store.record_publish_failure(
            event.event_id,
            error_message="RuntimeError: broker timeout",
            max_attempts=2,
            retry_delay_for_attempt=lambda _: 45,
            now=datetime(2026, 2, 1, 10, 6, tzinfo=UTC),
        )
        self.assertIsNotNone(second_transition)
        assert second_transition is not None
        self.assertEqual(second_transition.status, "failed")
        self.assertEqual(second_transition.publish_attempts, 2)
        self.assertIsNone(second_transition.next_available_at)
        self.assertEqual(second_transition.last_error, "dead_letter:RuntimeError: broker timeout")
        self.assertEqual(second_transition.dead_lettered_at, datetime(2026, 2, 1, 10, 6, tzinfo=UTC))

        with closing(sqlite3.connect(self.db_path)) as connection:
            status, publish_attempts, failure_count, last_error, dead_lettered_at = connection.execute(
                """
                SELECT status, publish_attempts, failure_count, last_error, dead_lettered_at
                FROM outbox_events
                WHERE event_id = ?
                """,
                (event.event_id,),
            ).fetchone()
        self.assertEqual(status, "failed")
        self.assertEqual(publish_attempts, 2)
        self.assertEqual(failure_count, 2)
        self.assertEqual(last_error, "dead_letter:RuntimeError: broker timeout")
        self.assertEqual(dead_lettered_at, "2026-02-01 10:06:00")

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
