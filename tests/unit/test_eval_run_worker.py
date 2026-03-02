from __future__ import annotations

import json
import re
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

API_GATEWAY_DIR = ROOT / "apps" / "api-gateway"
if str(API_GATEWAY_DIR) not in sys.path:
    sys.path.insert(0, str(API_GATEWAY_DIR))

from api_gateway.app import EvalRunWorker
from api_gateway.repository import SQLiteJobIngestionRepository

MIGRATIONS_DIR = ROOT / "infra" / "migrations"
UP_MARKER = re.compile(r"^\s*--\s*\+goose\s+Up\s*$")
DOWN_MARKER = re.compile(r"^\s*--\s*\+goose\s+Down\s*$")


def _parse_up_sql(path: Path) -> str:
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    up_idx = None
    down_idx = None

    for idx, line in enumerate(lines):
        if up_idx is None and UP_MARKER.match(line):
            up_idx = idx
            continue
        if up_idx is not None and DOWN_MARKER.match(line):
            down_idx = idx
            break

    if up_idx is None:
        raise RuntimeError(f"{path.name}: missing '-- +goose Up' marker")
    if down_idx is None:
        raise RuntimeError(f"{path.name}: missing '-- +goose Down' marker")

    sql = "".join(lines[up_idx + 1 : down_idx]).strip()
    if not sql:
        raise RuntimeError(f"{path.name}: Up section is empty")
    return sql + "\n"


def _bootstrap_sqlite_schema(db_path: Path) -> None:
    migration_files = sorted(MIGRATIONS_DIR.glob("*.sql"))
    if not migration_files:
        raise RuntimeError(f"No migrations found in {MIGRATIONS_DIR}")

    with closing(sqlite3.connect(db_path)) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        for migration in migration_files:
            conn.executescript(_parse_up_sql(migration))
        conn.commit()


class EvalRunWorkerTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory(prefix="eval-run-worker-")
        self.db_path = Path(self._tmpdir.name) / "jobcoach.sqlite3"
        _bootstrap_sqlite_schema(self.db_path)
        self.repository = SQLiteJobIngestionRepository(self.db_path)

    def tearDown(self) -> None:
        self._tmpdir.cleanup()

    def _load_eval_run_row(self, *, eval_run_id: str) -> sqlite3.Row | None:
        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.row_factory = sqlite3.Row
            return conn.execute(
                """
                SELECT eval_run_id, suite, status, metrics_json, error_code, error_message, started_at, completed_at
                FROM eval_runs
                WHERE eval_run_id = ?
                """,
                (eval_run_id,),
            ).fetchone()

    def _load_eval_run_outbox_rows(self, *, eval_run_id: str) -> list[sqlite3.Row]:
        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.row_factory = sqlite3.Row
            return conn.execute(
                """
                SELECT event_id, event_type, payload_json, status
                FROM outbox_events
                WHERE aggregate_type = 'eval_run' AND aggregate_id = ?
                ORDER BY created_at ASC, event_id ASC
                """,
                (eval_run_id,),
            ).fetchall()

    def test_run_once_claims_and_completes_succeeded_eval_run(self) -> None:
        create_result = self.repository.create_or_get_eval_run(
            idempotency_key="worker-success-001",
            request_payload={"suite": "feedback_quality_v1"},
            suite="feedback_quality_v1",
        )
        self.assertEqual(create_result.status, "created")
        assert create_result.eval_run is not None
        eval_run_id = str(create_result.eval_run["eval_run_id"])

        succeeded_metrics: dict[str, Any] = {
            "suite": "feedback_quality_v1",
            "passed": True,
            "aggregate": {"overall_feedback_quality": 0.98},
            "failed_threshold_count": 0,
            "failed_threshold_metrics": [],
            "case_count": 3,
        }

        worker = EvalRunWorker(
            repository=self.repository,
            suite_executor=lambda _: ("succeeded", succeeded_metrics, None),
        )
        run_result = worker.run_once(limit=1)
        self.assertEqual(run_result.claimed_count, 1)
        self.assertEqual(run_result.terminal_count, 1)
        self.assertEqual(run_result.skipped_count, 0)

        row = self._load_eval_run_row(eval_run_id=eval_run_id)
        self.assertIsNotNone(row)
        assert row is not None
        self.assertEqual(str(row["status"]), "succeeded")
        self.assertEqual(json.loads(str(row["metrics_json"])), succeeded_metrics)
        self.assertIsNone(row["error_code"])
        self.assertIsNone(row["error_message"])
        self.assertIsInstance(row["started_at"], str)
        self.assertIsInstance(row["completed_at"], str)

        outbox_rows = self._load_eval_run_outbox_rows(eval_run_id=eval_run_id)
        self.assertEqual({str(item["event_type"]) for item in outbox_rows}, {"eval_run.queued", "eval_run.succeeded"})

    def test_run_once_claims_and_completes_failed_eval_run(self) -> None:
        create_result = self.repository.create_or_get_eval_run(
            idempotency_key="worker-failed-001",
            request_payload={"suite": "trajectory_quality_v1"},
            suite="trajectory_quality_v1",
        )
        self.assertEqual(create_result.status, "created")
        assert create_result.eval_run is not None
        eval_run_id = str(create_result.eval_run["eval_run_id"])

        failed_metrics: dict[str, Any] = {
            "suite": "trajectory_quality_v1",
            "passed": False,
            "aggregate": {"overall_trajectory_quality": 0.8},
            "failed_threshold_count": 1,
            "failed_threshold_metrics": ["overall_trajectory_quality"],
            "case_count": 4,
        }

        worker = EvalRunWorker(
            repository=self.repository,
            suite_executor=lambda _: (
                "failed",
                failed_metrics,
                {"code": "benchmark_threshold_failed", "message": "Threshold gate not satisfied"},
            ),
        )
        run_result = worker.run_once(limit=1)
        self.assertEqual(run_result.claimed_count, 1)
        self.assertEqual(run_result.terminal_count, 1)
        self.assertEqual(run_result.skipped_count, 0)

        row = self._load_eval_run_row(eval_run_id=eval_run_id)
        self.assertIsNotNone(row)
        assert row is not None
        self.assertEqual(str(row["status"]), "failed")
        self.assertEqual(json.loads(str(row["metrics_json"])), failed_metrics)
        self.assertEqual(str(row["error_code"]), "benchmark_threshold_failed")
        self.assertEqual(str(row["error_message"]), "Threshold gate not satisfied")
        self.assertIsInstance(row["started_at"], str)
        self.assertIsInstance(row["completed_at"], str)

        outbox_rows = self._load_eval_run_outbox_rows(eval_run_id=eval_run_id)
        self.assertEqual({str(item["event_type"]) for item in outbox_rows}, {"eval_run.queued", "eval_run.failed"})
        failed_row = next(item for item in outbox_rows if str(item["event_type"]) == "eval_run.failed")
        failed_payload = json.loads(str(failed_row["payload_json"]))
        self.assertEqual(
            failed_payload.get("error"),
            {"code": "benchmark_threshold_failed", "message": "Threshold gate not satisfied"},
        )

    def test_run_once_is_noop_when_no_queued_runs(self) -> None:
        worker = EvalRunWorker(
            repository=self.repository,
            suite_executor=lambda _: ("succeeded", {"suite": "job_extraction_v1"}, None),
        )
        run_result = worker.run_once(limit=3)
        self.assertEqual(run_result.claimed_count, 0)
        self.assertEqual(run_result.terminal_count, 0)
        self.assertEqual(run_result.skipped_count, 0)

    def test_run_once_uses_deterministic_queue_order_and_repeat_polls_are_safe(self) -> None:
        first_create = self.repository.create_or_get_eval_run(
            idempotency_key="worker-order-001",
            request_payload={"suite": "feedback_quality_v1"},
            suite="feedback_quality_v1",
        )
        second_create = self.repository.create_or_get_eval_run(
            idempotency_key="worker-order-002",
            request_payload={"suite": "trajectory_quality_v1"},
            suite="trajectory_quality_v1",
        )
        self.assertEqual(first_create.status, "created")
        self.assertEqual(second_create.status, "created")
        assert first_create.eval_run is not None
        assert second_create.eval_run is not None
        first_eval_run_id = str(first_create.eval_run["eval_run_id"])
        second_eval_run_id = str(second_create.eval_run["eval_run_id"])

        with closing(sqlite3.connect(self.db_path)) as conn:
            with conn:
                conn.execute(
                    "UPDATE eval_runs SET created_at = '2026-03-01 00:00:01' WHERE eval_run_id = ?",
                    (first_eval_run_id,),
                )
                conn.execute(
                    "UPDATE eval_runs SET created_at = '2026-03-01 00:00:02' WHERE eval_run_id = ?",
                    (second_eval_run_id,),
                )

        execution_order: list[str] = []

        def _suite_executor(suite: str) -> tuple[str, dict[str, Any], dict[str, str] | None]:
            execution_order.append(suite)
            return (
                "succeeded",
                {
                    "suite": suite,
                    "passed": True,
                    "aggregate": {},
                    "failed_threshold_count": 0,
                    "failed_threshold_metrics": [],
                    "case_count": 0,
                },
                None,
            )

        worker = EvalRunWorker(repository=self.repository, suite_executor=_suite_executor)
        first_result = worker.run_once(limit=1)
        second_result = worker.run_once(limit=1)
        replay_result = worker.run_once(limit=1)

        self.assertEqual(first_result.claimed_count, 1)
        self.assertEqual(second_result.claimed_count, 1)
        self.assertEqual(replay_result.claimed_count, 0)
        self.assertEqual(execution_order, ["feedback_quality_v1", "trajectory_quality_v1"])

        first_outbox_rows = self._load_eval_run_outbox_rows(eval_run_id=first_eval_run_id)
        second_outbox_rows = self._load_eval_run_outbox_rows(eval_run_id=second_eval_run_id)
        self.assertEqual(len(first_outbox_rows), 2)
        self.assertEqual(len(second_outbox_rows), 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
