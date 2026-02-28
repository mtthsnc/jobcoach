from __future__ import annotations

import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

from services.orchestrator.outbox.sqlite_outbox import OutboxEvent, SQLiteOutboxStore


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
                    last_error TEXT,
                    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX idx_outbox_events_status_available_at ON outbox_events (status, available_at);
                CREATE INDEX idx_outbox_events_aggregate ON outbox_events (aggregate_type, aggregate_id);
                """
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
