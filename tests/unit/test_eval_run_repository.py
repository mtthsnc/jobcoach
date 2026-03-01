from __future__ import annotations

import json
import re
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

API_GATEWAY_DIR = ROOT / "apps" / "api-gateway"
if str(API_GATEWAY_DIR) not in sys.path:
    sys.path.insert(0, str(API_GATEWAY_DIR))

from api_gateway.app import _validate_run_eval_request_payload
from api_gateway.repository import SQLiteJobIngestionRepository

MIGRATIONS_DIR = ROOT / "infra" / "migrations"
UP_MARKER = re.compile(r"^\s*--\s*\+goose\s+Up\s*$")
DOWN_MARKER = re.compile(r"^\s*--\s*\+goose\s+Down\s*$")
EVAL_SUITES = (
    "job_extraction_v1",
    "candidate_parse_v1",
    "interview_relevance_v1",
    "feedback_quality_v1",
    "trajectory_quality_v1",
    "negotiation_quality_v1",
)


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


class EvalRunRepositoryTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory(prefix="eval-run-repo-")
        self.db_path = Path(self._tmpdir.name) / "jobcoach.sqlite3"
        _bootstrap_sqlite_schema(self.db_path)
        self.repository = SQLiteJobIngestionRepository(self.db_path)

    def tearDown(self) -> None:
        self._tmpdir.cleanup()

    def _load_eval_run_outbox_events(self, *, eval_run_id: str) -> list[sqlite3.Row]:
        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT
                    event_id,
                    aggregate_type,
                    aggregate_id,
                    event_type,
                    payload_json,
                    status,
                    available_at
                FROM outbox_events
                WHERE aggregate_type = 'eval_run' AND aggregate_id = ?
                ORDER BY created_at ASC, event_id ASC
                """,
                (eval_run_id,),
            ).fetchall()
        return rows

    def test_eval_runs_table_accepts_expanded_suite_catalog(self) -> None:
        with closing(sqlite3.connect(self.db_path)) as conn:
            for idx, suite in enumerate(EVAL_SUITES):
                conn.execute(
                    """
                    INSERT INTO eval_runs (
                        eval_run_id,
                        suite,
                        status,
                        idempotency_key,
                        request_json
                    )
                    VALUES (?, ?, 'queued', ?, ?)
                    """,
                    (
                        f"eval_catalog_{idx}",
                        suite,
                        f"catalog-idem-{idx}",
                        f'{{"suite":"{suite}"}}',
                    ),
                )
            conn.commit()
            rows = conn.execute("SELECT suite FROM eval_runs ORDER BY suite ASC").fetchall()

        self.assertEqual([str(row[0]) for row in rows], sorted(EVAL_SUITES))

    def test_create_or_get_eval_run_replay_and_conflict_semantics(self) -> None:
        create_result = self.repository.create_or_get_eval_run(
            idempotency_key="eval-idempotency-001",
            request_payload={"suite": "feedback_quality_v1"},
            suite="feedback_quality_v1",
        )
        self.assertEqual(create_result.status, "created")
        self.assertIsNotNone(create_result.eval_run)
        assert create_result.eval_run is not None
        created_run_id = create_result.eval_run.get("eval_run_id")
        self.assertIsInstance(created_run_id, str)
        self.assertTrue(created_run_id)
        assert isinstance(created_run_id, str)
        self.assertEqual(create_result.eval_run.get("suite"), "feedback_quality_v1")
        self.assertEqual(create_result.eval_run.get("status"), "queued")
        self.assertEqual(create_result.eval_run.get("metrics"), {})

        replay_result = self.repository.create_or_get_eval_run(
            idempotency_key="eval-idempotency-001",
            request_payload={"suite": "feedback_quality_v1"},
            suite="feedback_quality_v1",
        )
        self.assertEqual(replay_result.status, "idempotent_replay")
        self.assertIsNotNone(replay_result.eval_run)
        assert replay_result.eval_run is not None
        self.assertEqual(replay_result.eval_run.get("eval_run_id"), created_run_id)
        self.assertEqual(replay_result.eval_run.get("suite"), "feedback_quality_v1")

        conflict_result = self.repository.create_or_get_eval_run(
            idempotency_key="eval-idempotency-001",
            request_payload={"suite": "trajectory_quality_v1"},
            suite="trajectory_quality_v1",
        )
        self.assertEqual(conflict_result.status, "idempotency_conflict")
        self.assertIsNotNone(conflict_result.eval_run)
        assert conflict_result.eval_run is not None
        self.assertEqual(conflict_result.eval_run.get("eval_run_id"), created_run_id)
        self.assertEqual(conflict_result.eval_run.get("suite"), "feedback_quality_v1")

        with closing(sqlite3.connect(self.db_path)) as conn:
            row = conn.execute("SELECT COUNT(*) FROM eval_runs").fetchone()
        self.assertIsNotNone(row)
        assert row is not None
        self.assertEqual(int(row[0]), 1)

        outbox_rows = self._load_eval_run_outbox_events(eval_run_id=created_run_id)
        self.assertEqual(len(outbox_rows), 1)
        queued_row = outbox_rows[0]
        self.assertEqual(queued_row["event_id"], f"evt_eval_run_{created_run_id}_queued")
        self.assertEqual(queued_row["event_type"], "eval_run.queued")
        self.assertEqual(queued_row["aggregate_type"], "eval_run")
        self.assertEqual(queued_row["aggregate_id"], created_run_id)
        self.assertEqual(queued_row["status"], "pending")
        queued_payload = json.loads(str(queued_row["payload_json"]))
        self.assertEqual(queued_payload.get("eval_run_id"), created_run_id)
        self.assertEqual(queued_payload.get("suite"), "feedback_quality_v1")
        self.assertEqual(queued_payload.get("status"), "queued")
        self.assertIn("created_at", queued_payload)
        self.assertNotIn("metrics", queued_payload)
        self.assertNotIn("error", queued_payload)

    def test_get_eval_run_by_id_returns_persisted_payload_and_none_for_unknown(self) -> None:
        create_result = self.repository.create_or_get_eval_run(
            idempotency_key="eval-read-001",
            request_payload={"suite": "job_extraction_v1"},
            suite="job_extraction_v1",
        )
        self.assertEqual(create_result.status, "created")
        assert create_result.eval_run is not None
        eval_run_id = str(create_result.eval_run["eval_run_id"])

        loaded = self.repository.get_eval_run_by_id(eval_run_id)
        self.assertIsNotNone(loaded)
        assert loaded is not None
        self.assertEqual(loaded.get("eval_run_id"), eval_run_id)
        self.assertEqual(loaded.get("suite"), "job_extraction_v1")
        self.assertEqual(loaded.get("status"), "queued")
        self.assertEqual(loaded.get("metrics"), {})
        self.assertIsInstance(loaded.get("created_at"), str)

        missing = self.repository.get_eval_run_by_id("eval_missing_001")
        self.assertIsNone(missing)

    def test_eval_run_transition_methods_persist_running_and_terminal_states(self) -> None:
        create_result = self.repository.create_or_get_eval_run(
            idempotency_key="eval-transition-001",
            request_payload={"suite": "interview_relevance_v1"},
            suite="interview_relevance_v1",
        )
        self.assertEqual(create_result.status, "created")
        assert create_result.eval_run is not None
        eval_run_id = str(create_result.eval_run["eval_run_id"])

        running_payload = self.repository.mark_eval_run_running(eval_run_id=eval_run_id)
        self.assertIsNotNone(running_payload)
        assert running_payload is not None
        self.assertEqual(running_payload.get("status"), "running")
        self.assertIsInstance(running_payload.get("started_at"), str)

        succeeded_metrics = {
            "suite": "interview_relevance_v1",
            "passed": True,
            "aggregate": {"overall_relevance": 1.0},
            "failed_threshold_count": 0,
            "failed_threshold_metrics": [],
            "case_count": 3,
        }
        terminal_payload = self.repository.complete_eval_run(
            eval_run_id=eval_run_id,
            status="succeeded",
            metrics=succeeded_metrics,
        )
        self.assertIsNotNone(terminal_payload)
        assert terminal_payload is not None
        self.assertEqual(terminal_payload.get("status"), "succeeded")
        self.assertEqual(terminal_payload.get("metrics"), succeeded_metrics)
        self.assertIsInstance(terminal_payload.get("completed_at"), str)
        self.assertIsNone(terminal_payload.get("error"))
        succeeded_outbox = self._load_eval_run_outbox_events(eval_run_id=eval_run_id)
        self.assertEqual(
            {str(row["event_type"]) for row in succeeded_outbox},
            {"eval_run.queued", "eval_run.succeeded"},
        )
        succeeded_terminal_row = next(row for row in succeeded_outbox if row["event_type"] == "eval_run.succeeded")
        succeeded_terminal_payload = json.loads(str(succeeded_terminal_row["payload_json"]))
        self.assertEqual(succeeded_terminal_payload.get("status"), "succeeded")
        self.assertEqual(succeeded_terminal_payload.get("metrics"), succeeded_metrics)
        self.assertNotIn("error", succeeded_terminal_payload)

        failed_create = self.repository.create_or_get_eval_run(
            idempotency_key="eval-transition-002",
            request_payload={"suite": "trajectory_quality_v1"},
            suite="trajectory_quality_v1",
        )
        self.assertEqual(failed_create.status, "created")
        assert failed_create.eval_run is not None
        failed_eval_run_id = str(failed_create.eval_run["eval_run_id"])
        self.repository.mark_eval_run_running(eval_run_id=failed_eval_run_id)

        failed_metrics = {
            "suite": "trajectory_quality_v1",
            "passed": False,
            "aggregate": {"overall_trajectory_quality": 0.82},
            "failed_threshold_count": 1,
            "failed_threshold_metrics": ["overall_trajectory_quality"],
            "case_count": 4,
        }
        failed_payload = self.repository.complete_eval_run(
            eval_run_id=failed_eval_run_id,
            status="failed",
            metrics=failed_metrics,
            error_code="benchmark_threshold_failed",
            error_message="Threshold gate not satisfied",
        )
        self.assertIsNotNone(failed_payload)
        assert failed_payload is not None
        self.assertEqual(failed_payload.get("status"), "failed")
        self.assertEqual(failed_payload.get("metrics"), failed_metrics)
        self.assertEqual(
            failed_payload.get("error"),
            {"code": "benchmark_threshold_failed", "message": "Threshold gate not satisfied"},
        )
        self.assertIsInstance(failed_payload.get("started_at"), str)
        self.assertIsInstance(failed_payload.get("completed_at"), str)
        failed_outbox = self._load_eval_run_outbox_events(eval_run_id=failed_eval_run_id)
        self.assertEqual(
            {str(row["event_type"]) for row in failed_outbox},
            {"eval_run.queued", "eval_run.failed"},
        )
        failed_terminal_row = next(row for row in failed_outbox if row["event_type"] == "eval_run.failed")
        failed_terminal_payload = json.loads(str(failed_terminal_row["payload_json"]))
        self.assertEqual(failed_terminal_payload.get("status"), "failed")
        self.assertEqual(failed_terminal_payload.get("metrics"), failed_metrics)
        self.assertEqual(
            failed_terminal_payload.get("error"),
            {"code": "benchmark_threshold_failed", "message": "Threshold gate not satisfied"},
        )

    def test_complete_eval_run_terminal_event_is_not_duplicated_on_retry(self) -> None:
        create_result = self.repository.create_or_get_eval_run(
            idempotency_key="eval-terminal-dedup-001",
            request_payload={"suite": "trajectory_quality_v1"},
            suite="trajectory_quality_v1",
        )
        self.assertEqual(create_result.status, "created")
        assert create_result.eval_run is not None
        eval_run_id = str(create_result.eval_run["eval_run_id"])

        self.repository.mark_eval_run_running(eval_run_id=eval_run_id)
        first_terminal_payload = self.repository.complete_eval_run(
            eval_run_id=eval_run_id,
            status="failed",
            metrics={
                "suite": "trajectory_quality_v1",
                "passed": False,
                "aggregate": {"overall_trajectory_quality": 0.8},
                "failed_threshold_count": 1,
                "failed_threshold_metrics": ["overall_trajectory_quality"],
                "case_count": 4,
            },
            error_code="benchmark_threshold_failed",
            error_message="Threshold gate not satisfied",
        )
        self.assertIsNotNone(first_terminal_payload)

        retry_terminal_payload = self.repository.complete_eval_run(
            eval_run_id=eval_run_id,
            status="failed",
            metrics={
                "suite": "trajectory_quality_v1",
                "passed": False,
                "aggregate": {"overall_trajectory_quality": 0.1},
                "failed_threshold_count": 1,
                "failed_threshold_metrics": ["overall_trajectory_quality"],
                "case_count": 4,
            },
            error_code="other_error_code",
            error_message="Should not overwrite terminal state",
        )
        self.assertIsNotNone(retry_terminal_payload)
        assert retry_terminal_payload is not None
        self.assertEqual(retry_terminal_payload.get("status"), "failed")
        self.assertEqual(
            retry_terminal_payload.get("error"),
            {"code": "benchmark_threshold_failed", "message": "Threshold gate not satisfied"},
        )

        outbox_rows = self._load_eval_run_outbox_events(eval_run_id=eval_run_id)
        self.assertEqual(
            {str(row["event_type"]) for row in outbox_rows},
            {"eval_run.queued", "eval_run.failed"},
        )

    def test_validate_run_eval_request_payload_accepts_expanded_suites(self) -> None:
        for suite in EVAL_SUITES:
            self.assertEqual(_validate_run_eval_request_payload({"suite": suite}), [])

        invalid_suite_errors = _validate_run_eval_request_payload({"suite": "unknown_suite"})
        self.assertEqual(len(invalid_suite_errors), 1)
        self.assertEqual(invalid_suite_errors[0]["field"], "suite")

        missing_suite_errors = _validate_run_eval_request_payload({})
        self.assertEqual(len(missing_suite_errors), 1)
        self.assertEqual(missing_suite_errors[0]["field"], "suite")


if __name__ == "__main__":
    unittest.main(verbosity=2)
