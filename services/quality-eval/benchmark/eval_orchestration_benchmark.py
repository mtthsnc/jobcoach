#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
import tempfile
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT_DIR = Path(__file__).resolve().parents[3]
API_GATEWAY_DIR = ROOT_DIR / "apps" / "api-gateway"
MIGRATIONS_DIR = ROOT_DIR / "infra" / "migrations"
FIXTURE_DIR = ROOT_DIR / "tests" / "unit" / "fixtures" / "eval_orchestration"
DEFAULT_REPORT_PATH = ROOT_DIR / ".tmp" / "eval-orchestration-benchmark-report.json"

UP_MARKER = re.compile(r"^\s*--\s*\+goose\s+Up\s*$")
DOWN_MARKER = re.compile(r"^\s*--\s*\+goose\s+Down\s*$")

DEFAULT_THRESHOLDS = {
    "transition_correctness_rate": 1.0,
    "idempotency_correctness_rate": 1.0,
    "lifecycle_event_integrity_rate": 1.0,
    "overall_eval_orchestration_quality": 1.0,
}

if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))
if str(API_GATEWAY_DIR) not in sys.path:
    sys.path.insert(0, str(API_GATEWAY_DIR))

from api_gateway.app import EvalRunWorker
from api_gateway.repository import SQLiteJobIngestionRepository


@dataclass(frozen=True)
class BenchmarkCase:
    case_id: str
    suite: str
    conflict_suite: str
    request_payload: dict[str, Any]
    terminal_status: str
    terminal_metrics: dict[str, Any]
    terminal_error: dict[str, str] | None


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


def _load_benchmark_cases(fixtures_dir: Path) -> list[BenchmarkCase]:
    fixture_paths = sorted(fixtures_dir.glob("benchmark_*.json"))
    if not fixture_paths:
        raise RuntimeError(f"No benchmark fixtures found under {fixtures_dir}")

    cases: list[BenchmarkCase] = []
    for fixture_path in fixture_paths:
        raw_case = json.loads(fixture_path.read_text(encoding="utf-8"))
        terminal_status = str(raw_case.get("terminal_status", "")).strip()
        if terminal_status not in {"succeeded", "failed"}:
            raise RuntimeError(f"{fixture_path.name}: terminal_status must be succeeded|failed")

        raw_error = raw_case.get("terminal_error")
        terminal_error = None
        if isinstance(raw_error, dict):
            terminal_error = {
                "code": str(raw_error.get("code", "")),
                "message": str(raw_error.get("message", "")),
            }

        cases.append(
            BenchmarkCase(
                case_id=str(raw_case["case_id"]),
                suite=str(raw_case["suite"]),
                conflict_suite=str(raw_case["conflict_suite"]),
                request_payload=dict(raw_case.get("request_payload", {})),
                terminal_status=terminal_status,
                terminal_metrics=dict(raw_case.get("terminal_metrics", {})),
                terminal_error=terminal_error,
            )
        )
    return cases


def _mean(values: list[float]) -> float:
    if not values:
        return 0.0
    return sum(values) / len(values)


def _load_outbox_rows(*, db_path: Path, eval_run_id: str) -> list[sqlite3.Row]:
    with closing(sqlite3.connect(db_path)) as conn:
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


def _count_eval_runs_by_idempotency_key(*, db_path: Path, idempotency_key: str) -> int:
    with closing(sqlite3.connect(db_path)) as conn:
        row = conn.execute(
            "SELECT COUNT(*) FROM eval_runs WHERE idempotency_key = ?",
            (idempotency_key,),
        ).fetchone()
    if row is None:
        return 0
    return int(row[0])


def run_benchmark(
    *,
    fixtures_dir: Path = FIXTURE_DIR,
    thresholds: dict[str, float] | None = None,
) -> tuple[dict[str, Any], bool]:
    active_thresholds = dict(DEFAULT_THRESHOLDS)
    if thresholds:
        active_thresholds.update(thresholds)

    cases = _load_benchmark_cases(fixtures_dir)

    transition_scores: list[float] = []
    idempotency_scores: list[float] = []
    lifecycle_event_scores: list[float] = []
    case_reports: list[dict[str, Any]] = []

    with tempfile.TemporaryDirectory(prefix="eval-orchestration-benchmark-") as tmpdir:
        db_path = Path(tmpdir) / "jobcoach.sqlite3"
        _bootstrap_sqlite_schema(db_path)
        repository = SQLiteJobIngestionRepository(db_path)

        for benchmark_case in cases:
            idempotency_key = f"eval-orch-{benchmark_case.case_id}"
            conflict_payload = {"suite": benchmark_case.conflict_suite}

            create_result = repository.create_or_get_eval_run(
                idempotency_key=idempotency_key,
                request_payload=benchmark_case.request_payload,
                suite=benchmark_case.suite,
            )
            created_payload = create_result.eval_run if isinstance(create_result.eval_run, dict) else {}
            eval_run_id = str(created_payload.get("eval_run_id", "")).strip()

            replay_result = repository.create_or_get_eval_run(
                idempotency_key=idempotency_key,
                request_payload=benchmark_case.request_payload,
                suite=benchmark_case.suite,
            )
            conflict_result = repository.create_or_get_eval_run(
                idempotency_key=idempotency_key,
                request_payload=conflict_payload,
                suite=benchmark_case.conflict_suite,
            )

            def _suite_executor(_: str) -> tuple[str, dict[str, Any], dict[str, str] | None]:
                return benchmark_case.terminal_status, benchmark_case.terminal_metrics, benchmark_case.terminal_error

            worker = EvalRunWorker(repository=repository, suite_executor=_suite_executor)
            worker_result = worker.run_once(limit=1) if eval_run_id else None
            terminal_payload = repository.get_eval_run_by_id(eval_run_id) if eval_run_id else None
            retry_worker_result = worker.run_once(limit=1) if eval_run_id else None
            retry_payload = repository.get_eval_run_by_id(eval_run_id) if eval_run_id else None

            outbox_rows = _load_outbox_rows(db_path=db_path, eval_run_id=eval_run_id) if eval_run_id else []
            eval_run_row_count = _count_eval_runs_by_idempotency_key(db_path=db_path, idempotency_key=idempotency_key)

            create_status_pass = (
                create_result.status == "created"
                and bool(eval_run_id)
                and created_payload.get("status") == "queued"
                and created_payload.get("suite") == benchmark_case.suite
                and isinstance(created_payload.get("created_at"), str)
            )
            replay_pass = (
                replay_result.status == "idempotent_replay"
                and isinstance(replay_result.eval_run, dict)
                and str(replay_result.eval_run.get("eval_run_id", "")) == eval_run_id
                and str(replay_result.eval_run.get("suite", "")) == benchmark_case.suite
            )
            conflict_pass = (
                conflict_result.status == "idempotency_conflict"
                and isinstance(conflict_result.eval_run, dict)
                and str(conflict_result.eval_run.get("eval_run_id", "")) == eval_run_id
                and str(conflict_result.eval_run.get("suite", "")) == benchmark_case.suite
            )
            idempotency_row_count_pass = eval_run_row_count == 1
            idempotency_pass = create_status_pass and replay_pass and conflict_pass and idempotency_row_count_pass

            worker_claim_pass = (
                worker_result is not None
                and int(worker_result.claimed_count) == 1
                and int(worker_result.terminal_count) == 1
                and int(worker_result.skipped_count) == 0
            )
            running_pass = isinstance(terminal_payload, dict) and isinstance(terminal_payload.get("started_at"), str)
            terminal_pass = (
                isinstance(terminal_payload, dict)
                and terminal_payload.get("status") == benchmark_case.terminal_status
                and terminal_payload.get("metrics") == benchmark_case.terminal_metrics
                and isinstance(terminal_payload.get("completed_at"), str)
            )
            if benchmark_case.terminal_status == "failed":
                terminal_error_pass = isinstance(terminal_payload, dict) and terminal_payload.get("error") == (
                    benchmark_case.terminal_error or {}
                )
            else:
                terminal_error_pass = isinstance(terminal_payload, dict) and terminal_payload.get("error") is None
            retry_immutability_pass = (
                isinstance(retry_payload, dict)
                and retry_payload.get("status") == benchmark_case.terminal_status
                and retry_payload.get("metrics") == benchmark_case.terminal_metrics
                and retry_payload.get("error") == (terminal_payload or {}).get("error")
                and retry_worker_result is not None
                and int(retry_worker_result.claimed_count) == 0
                and int(retry_worker_result.terminal_count) == 0
                and int(retry_worker_result.skipped_count) == 0
            )
            transition_pass = worker_claim_pass and running_pass and terminal_pass and terminal_error_pass and retry_immutability_pass

            event_types = {str(row["event_type"]) for row in outbox_rows}
            event_count_pass = len(outbox_rows) == 2
            event_type_pass = event_types == {"eval_run.queued", f"eval_run.{benchmark_case.terminal_status}"}
            row_by_event_type = {str(row["event_type"]): row for row in outbox_rows}

            queued_row = row_by_event_type.get("eval_run.queued")
            terminal_event_key = f"eval_run.{benchmark_case.terminal_status}"
            terminal_row = row_by_event_type.get(terminal_event_key)

            queued_payload = (
                json.loads(str(queued_row["payload_json"]))
                if queued_row is not None and isinstance(queued_row["payload_json"], str)
                else {}
            )
            terminal_event_payload = (
                json.loads(str(terminal_row["payload_json"]))
                if terminal_row is not None and isinstance(terminal_row["payload_json"], str)
                else {}
            )

            queued_event_pass = (
                queued_row is not None
                and str(queued_row["event_id"]) == f"evt_eval_run_{eval_run_id}_queued"
                and str(queued_row["aggregate_type"]) == "eval_run"
                and str(queued_row["aggregate_id"]) == eval_run_id
                and str(queued_row["status"]) == "pending"
                and queued_payload.get("eval_run_id") == eval_run_id
                and queued_payload.get("suite") == benchmark_case.suite
                and queued_payload.get("status") == "queued"
                and isinstance(queued_payload.get("created_at"), str)
                and "metrics" not in queued_payload
                and "error" not in queued_payload
                and isinstance(queued_row["available_at"], str)
                and bool(str(queued_row["available_at"]).strip())
            )

            if benchmark_case.terminal_status == "failed":
                terminal_error_event_pass = terminal_event_payload.get("error") == (benchmark_case.terminal_error or {})
            else:
                terminal_error_event_pass = "error" not in terminal_event_payload

            terminal_event_pass = (
                terminal_row is not None
                and str(terminal_row["event_id"]) == f"evt_eval_run_{eval_run_id}_{benchmark_case.terminal_status}"
                and str(terminal_row["aggregate_type"]) == "eval_run"
                and str(terminal_row["aggregate_id"]) == eval_run_id
                and str(terminal_row["status"]) == "pending"
                and terminal_event_payload.get("eval_run_id") == eval_run_id
                and terminal_event_payload.get("suite") == benchmark_case.suite
                and terminal_event_payload.get("status") == benchmark_case.terminal_status
                and terminal_event_payload.get("metrics") == benchmark_case.terminal_metrics
                and isinstance(terminal_event_payload.get("started_at"), str)
                and isinstance(terminal_event_payload.get("completed_at"), str)
                and isinstance(terminal_row["available_at"], str)
                and bool(str(terminal_row["available_at"]).strip())
                and terminal_error_event_pass
            )
            lifecycle_event_integrity_pass = event_count_pass and event_type_pass and queued_event_pass and terminal_event_pass

            transition_scores.append(1.0 if transition_pass else 0.0)
            idempotency_scores.append(1.0 if idempotency_pass else 0.0)
            lifecycle_event_scores.append(1.0 if lifecycle_event_integrity_pass else 0.0)
            case_quality_score = _mean(
                [
                    1.0 if transition_pass else 0.0,
                    1.0 if idempotency_pass else 0.0,
                    1.0 if lifecycle_event_integrity_pass else 0.0,
                ]
            )

            case_reports.append(
                {
                    "case_id": benchmark_case.case_id,
                    "suite": benchmark_case.suite,
                    "conflict_suite": benchmark_case.conflict_suite,
                    "eval_run_id": eval_run_id,
                    "terminal_status": benchmark_case.terminal_status,
                    "worker_claimed_count": int(worker_result.claimed_count) if worker_result is not None else 0,
                    "transition_pass": transition_pass,
                    "idempotency_pass": idempotency_pass,
                    "lifecycle_event_integrity_pass": lifecycle_event_integrity_pass,
                    "event_types": sorted(event_types),
                    "event_count": len(outbox_rows),
                    "eval_run_row_count_for_idempotency_key": eval_run_row_count,
                    "case_quality_score": round(case_quality_score, 3),
                }
            )

    aggregate = {
        "transition_correctness_rate": round(_mean(transition_scores), 3),
        "idempotency_correctness_rate": round(_mean(idempotency_scores), 3),
        "lifecycle_event_integrity_rate": round(_mean(lifecycle_event_scores), 3),
    }
    aggregate["overall_eval_orchestration_quality"] = round(
        _mean(
            [
                aggregate["transition_correctness_rate"],
                aggregate["idempotency_correctness_rate"],
                aggregate["lifecycle_event_integrity_rate"],
            ]
        ),
        3,
    )

    failed_thresholds: list[dict[str, Any]] = []
    for metric_name, threshold in active_thresholds.items():
        actual = float(aggregate.get(metric_name, 0.0))
        if actual < threshold:
            failed_thresholds.append(
                {
                    "metric": metric_name,
                    "actual": round(actual, 3),
                    "threshold": round(float(threshold), 3),
                }
            )

    passed = len(failed_thresholds) == 0
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "fixtures_dir": str(fixtures_dir),
        "thresholds": {name: round(float(value), 3) for name, value in active_thresholds.items()},
        "aggregate": aggregate,
        "failed_thresholds": failed_thresholds,
        "passed": passed,
        "case_count": len(case_reports),
        "cases": case_reports,
    }
    return report, passed


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run deterministic eval-orchestration benchmark threshold gate.")
    parser.add_argument("--fixtures-dir", default=str(FIXTURE_DIR), help="Directory containing benchmark_*.json fixtures")
    parser.add_argument("--report-path", default=str(DEFAULT_REPORT_PATH), help="Path to write JSON benchmark report")
    parser.add_argument(
        "--min-transition-correctness-rate",
        type=float,
        default=DEFAULT_THRESHOLDS["transition_correctness_rate"],
    )
    parser.add_argument(
        "--min-idempotency-correctness-rate",
        type=float,
        default=DEFAULT_THRESHOLDS["idempotency_correctness_rate"],
    )
    parser.add_argument(
        "--min-lifecycle-event-integrity-rate",
        type=float,
        default=DEFAULT_THRESHOLDS["lifecycle_event_integrity_rate"],
    )
    parser.add_argument(
        "--min-overall-eval-orchestration-quality",
        type=float,
        default=DEFAULT_THRESHOLDS["overall_eval_orchestration_quality"],
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    report, passed = run_benchmark(
        fixtures_dir=Path(args.fixtures_dir),
        thresholds={
            "transition_correctness_rate": args.min_transition_correctness_rate,
            "idempotency_correctness_rate": args.min_idempotency_correctness_rate,
            "lifecycle_event_integrity_rate": args.min_lifecycle_event_integrity_rate,
            "overall_eval_orchestration_quality": args.min_overall_eval_orchestration_quality,
        },
    )

    report_path = Path(args.report_path)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
