#!/usr/bin/env python3
from __future__ import annotations

import argparse
import io
import json
import re
import sqlite3
import sys
import tempfile
import time
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote


ROOT_DIR = Path(__file__).resolve().parents[3]
API_GATEWAY_DIR = ROOT_DIR / "apps" / "api-gateway"
MIGRATIONS_DIR = ROOT_DIR / "infra" / "migrations"
DEFAULT_REPORT_PATH = ROOT_DIR / ".tmp" / "api-read-latency-benchmark-report.json"

UP_MARKER = re.compile(r"^\s*--\s*\+goose\s+Up\s*$")
DOWN_MARKER = re.compile(r"^\s*--\s*\+goose\s+Down\s*$")
BENCHMARK_BEARER_TOKEN = "benchmark-token"
DEFAULT_ITERATIONS = 7

DEFAULT_THRESHOLDS = {
    "read_path_p95_ms": 400.0,
    "read_path_success_rate": 1.0,
}

if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))
if str(API_GATEWAY_DIR) not in sys.path:
    sys.path.insert(0, str(API_GATEWAY_DIR))

from api_gateway.app import create_app


@dataclass(frozen=True)
class ReadPathCase:
    case_id: str
    path: str
    expected_status: int = 200
    add_default_auth: bool = True


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

    with closing(sqlite3.connect(db_path)) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        for migration in migration_files:
            connection.executescript(_parse_up_sql(migration))
        connection.commit()


def _request(
    app: Any,
    *,
    method: str,
    path: str,
    body: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    add_default_auth: bool = True,
) -> tuple[int, dict[str, str], dict[str, Any]]:
    body_bytes = b""
    if body is not None:
        body_bytes = json.dumps(body, separators=(",", ":"), ensure_ascii=False).encode("utf-8")

    path_info, _, query_string = path.partition("?")
    environ: dict[str, Any] = {
        "REQUEST_METHOD": method,
        "PATH_INFO": path_info,
        "QUERY_STRING": query_string,
        "wsgi.input": io.BytesIO(body_bytes),
        "CONTENT_LENGTH": str(len(body_bytes)),
        "CONTENT_TYPE": "application/json",
    }

    request_headers = dict(headers or {})
    if add_default_auth and path_info.startswith("/v1") and "Authorization" not in request_headers:
        request_headers["Authorization"] = f"Bearer {BENCHMARK_BEARER_TOKEN}"

    for key, value in request_headers.items():
        normalized = key.upper().replace("-", "_")
        environ[f"HTTP_{normalized}"] = value

    captured: dict[str, Any] = {"status": "500 Internal Server Error", "headers": []}

    def start_response(status: str, response_headers: list[tuple[str, str]]) -> None:
        captured["status"] = status
        captured["headers"] = response_headers

    chunks = app(environ, start_response)
    raw = b"".join(chunks)
    payload = json.loads(raw.decode("utf-8")) if raw else {}
    status_code = int(str(captured["status"]).split(" ", 1)[0])
    response_headers = {name: value for name, value in captured["headers"]}
    return status_code, response_headers, payload


def _expect_status(status: int, expected: int, *, context: str, body: dict[str, Any]) -> None:
    if status != expected:
        raise RuntimeError(f"{context}: expected {expected}, got {status}, body={body}")


def _required_string(value: Any, *, context: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise RuntimeError(f"{context}: expected non-empty string")
    return normalized


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = max(0.0, min(1.0, percentile)) * (len(ordered) - 1)
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return (ordered[lower] * (1.0 - weight)) + (ordered[upper] * weight)


def _mean(values: list[float]) -> float:
    if not values:
        return 0.0
    return sum(values) / len(values)


def _seed_read_paths(app: Any) -> list[ReadPathCase]:
    create_job_status, _, create_job_body = _request(
        app,
        method="POST",
        path="/v1/job-ingestions",
        body={
            "source_type": "text",
            "source_value": (
                "Senior Backend Engineer\n"
                "Responsibilities:\n"
                "- Build API services.\n"
                "- Improve reliability and observability.\n"
                "Requirements:\n"
                "- Python\n"
                "- SQL\n"
            ),
        },
        headers={"Idempotency-Key": "latency-job-001"},
    )
    _expect_status(create_job_status, 202, context="seed job ingestion", body=create_job_body)
    job_ingestion_id = _required_string(
        create_job_body.get("data", {}).get("ingestion_id"),
        context="seed job ingestion id",
    )

    get_job_status, _, get_job_body = _request(
        app,
        method="GET",
        path=f"/v1/job-ingestions/{job_ingestion_id}",
    )
    _expect_status(get_job_status, 200, context="seed job ingestion get", body=get_job_body)
    job_spec_id = _required_string(
        get_job_body.get("data", {}).get("result", {}).get("entity_id"),
        context="seed job spec id",
    )

    create_candidate_status, _, create_candidate_body = _request(
        app,
        method="POST",
        path="/v1/candidate-ingestions",
        body={
            "candidate_id": "cand_read_latency_001",
            "cv_text": (
                "Jamie Parker\n"
                "Senior Backend Engineer\n"
                "Built Python and SQL services with measurable latency and reliability gains."
            ),
            "target_roles": ["Senior Backend Engineer"],
            "story_notes": ["Improved p95 latency by 42%."],
        },
        headers={"Idempotency-Key": "latency-candidate-001"},
    )
    _expect_status(create_candidate_status, 202, context="seed candidate ingestion", body=create_candidate_body)
    candidate_ingestion_id = _required_string(
        create_candidate_body.get("data", {}).get("ingestion_id"),
        context="seed candidate ingestion id",
    )

    get_candidate_status, _, get_candidate_body = _request(
        app,
        method="GET",
        path=f"/v1/candidate-ingestions/{candidate_ingestion_id}",
    )
    _expect_status(get_candidate_status, 200, context="seed candidate ingestion get", body=get_candidate_body)
    candidate_id = _required_string(
        get_candidate_body.get("data", {}).get("result", {}).get("entity_id"),
        context="seed candidate id",
    )

    create_session_status, _, create_session_body = _request(
        app,
        method="POST",
        path="/v1/interview-sessions",
        body={
            "job_spec_id": job_spec_id,
            "candidate_id": candidate_id,
            "mode": "mock_interview",
        },
    )
    _expect_status(create_session_status, 201, context="seed interview session", body=create_session_body)
    session_id = _required_string(
        create_session_body.get("data", {}).get("session_id"),
        context="seed session id",
    )

    create_feedback_status, _, create_feedback_body = _request(
        app,
        method="POST",
        path="/v1/feedback-reports",
        body={"session_id": session_id},
        headers={"Idempotency-Key": "latency-feedback-001"},
    )
    _expect_status(create_feedback_status, 201, context="seed feedback report", body=create_feedback_body)
    feedback_report_id = _required_string(
        create_feedback_body.get("data", {}).get("feedback_report_id"),
        context="seed feedback report id",
    )

    target_role = "Senior Backend Engineer"
    create_trajectory_status, _, create_trajectory_body = _request(
        app,
        method="POST",
        path="/v1/trajectory-plans",
        body={"candidate_id": candidate_id, "target_role": target_role},
        headers={"Idempotency-Key": "latency-trajectory-001"},
    )
    _expect_status(create_trajectory_status, 201, context="seed trajectory plan", body=create_trajectory_body)
    trajectory_plan_id = _required_string(
        create_trajectory_body.get("data", {}).get("trajectory_plan_id"),
        context="seed trajectory plan id",
    )

    create_negotiation_status, _, create_negotiation_body = _request(
        app,
        method="POST",
        path="/v1/negotiation-plans",
        body={
            "candidate_id": candidate_id,
            "target_role": target_role,
            "current_base_salary": 165000,
            "target_base_salary": 190000,
            "offer_deadline_date": "2026-03-25",
        },
        headers={"Idempotency-Key": "latency-negotiation-001"},
    )
    _expect_status(create_negotiation_status, 201, context="seed negotiation plan", body=create_negotiation_body)
    negotiation_plan_id = _required_string(
        create_negotiation_body.get("data", {}).get("negotiation_plan_id"),
        context="seed negotiation plan id",
    )

    create_eval_status, _, create_eval_body = _request(
        app,
        method="POST",
        path="/v1/evals/run",
        body={"suite": "job_extraction_v1"},
        headers={"Idempotency-Key": "latency-eval-001"},
    )
    _expect_status(create_eval_status, 202, context="seed eval run", body=create_eval_body)
    eval_run_id = _required_string(
        create_eval_body.get("data", {}).get("eval_run_id"),
        context="seed eval run id",
    )

    quoted_target_role = quote(target_role, safe="")
    return [
        ReadPathCase(case_id="health", path="/health", add_default_auth=False),
        ReadPathCase(case_id="readiness", path="/readiness", add_default_auth=False),
        ReadPathCase(case_id="job_ingestion_get", path=f"/v1/job-ingestions/{job_ingestion_id}"),
        ReadPathCase(case_id="job_spec_get", path=f"/v1/job-specs/{job_spec_id}"),
        ReadPathCase(case_id="candidate_ingestion_get", path=f"/v1/candidate-ingestions/{candidate_ingestion_id}"),
        ReadPathCase(case_id="candidate_profile_get", path=f"/v1/candidates/{candidate_id}/profile"),
        ReadPathCase(case_id="candidate_storybank_get", path=f"/v1/candidates/{candidate_id}/storybank"),
        ReadPathCase(
            case_id="candidate_progress_dashboard_get",
            path=f"/v1/candidates/{candidate_id}/progress-dashboard?target_role={quoted_target_role}",
        ),
        ReadPathCase(case_id="interview_session_get", path=f"/v1/interview-sessions/{session_id}"),
        ReadPathCase(case_id="feedback_report_get", path=f"/v1/feedback-reports/{feedback_report_id}"),
        ReadPathCase(case_id="trajectory_plan_get", path=f"/v1/trajectory-plans/{trajectory_plan_id}"),
        ReadPathCase(case_id="negotiation_plan_get", path=f"/v1/negotiation-plans/{negotiation_plan_id}"),
        ReadPathCase(case_id="eval_run_get", path=f"/v1/evals/{eval_run_id}"),
    ]


def run_benchmark(
    *,
    thresholds: dict[str, float] | None = None,
    iterations: int = DEFAULT_ITERATIONS,
) -> tuple[dict[str, Any], bool]:
    active_thresholds = dict(DEFAULT_THRESHOLDS)
    if thresholds:
        active_thresholds.update(thresholds)

    normalized_iterations = max(1, int(iterations))
    case_reports: list[dict[str, Any]] = []
    all_latency_samples: list[float] = []
    successful_cases = 0

    with tempfile.TemporaryDirectory(prefix="api-read-latency-benchmark-") as tmpdir:
        db_path = Path(tmpdir) / "jobcoach.sqlite3"
        _bootstrap_sqlite_schema(db_path)
        app = create_app(
            db_path=db_path,
            auth_bypass_enabled=False,
            bearer_token=BENCHMARK_BEARER_TOKEN,
        )
        read_cases = _seed_read_paths(app)

        for read_case in read_cases:
            status_samples: list[int] = []
            latency_samples: list[float] = []
            error_codes: list[str] = []
            for _ in range(normalized_iterations):
                started_at = time.perf_counter()
                status, _, body = _request(
                    app,
                    method="GET",
                    path=read_case.path,
                    add_default_auth=read_case.add_default_auth,
                )
                elapsed_ms = (time.perf_counter() - started_at) * 1000.0
                latency_samples.append(elapsed_ms)
                all_latency_samples.append(elapsed_ms)
                status_samples.append(status)
                error_payload = body.get("error")
                if isinstance(error_payload, dict):
                    error_code = str(error_payload.get("code", "")).strip()
                    if error_code:
                        error_codes.append(error_code)

            case_pass = all(sample == read_case.expected_status for sample in status_samples)
            if case_pass:
                successful_cases += 1

            case_reports.append(
                {
                    "case_id": read_case.case_id,
                    "path": read_case.path,
                    "expected_status": read_case.expected_status,
                    "status_samples": status_samples,
                    "status_pass": case_pass,
                    "error_codes": sorted(set(error_codes)),
                    "latency_ms": {
                        "min": round(min(latency_samples), 3),
                        "p50": round(_percentile(latency_samples, 0.50), 3),
                        "p95": round(_percentile(latency_samples, 0.95), 3),
                        "max": round(max(latency_samples), 3),
                        "mean": round(_mean(latency_samples), 3),
                    },
                }
            )

    aggregate = {
        "read_path_success_rate": round(successful_cases / len(case_reports), 3) if case_reports else 0.0,
        "read_path_p50_ms": round(_percentile(all_latency_samples, 0.50), 3),
        "read_path_p95_ms": round(_percentile(all_latency_samples, 0.95), 3),
        "read_path_max_ms": round(max(all_latency_samples), 3) if all_latency_samples else 0.0,
        "read_path_mean_ms": round(_mean(all_latency_samples), 3),
    }

    failed_thresholds: list[dict[str, Any]] = []
    for metric_name, threshold in active_thresholds.items():
        actual = float(aggregate.get(metric_name, 0.0))
        if metric_name.endswith("_ms"):
            if actual > float(threshold):
                failed_thresholds.append(
                    {
                        "metric": metric_name,
                        "actual": round(actual, 3),
                        "threshold": round(float(threshold), 3),
                        "operator": "<=",
                    }
                )
        else:
            if actual < float(threshold):
                failed_thresholds.append(
                    {
                        "metric": metric_name,
                        "actual": round(actual, 3),
                        "threshold": round(float(threshold), 3),
                        "operator": ">=",
                    }
                )

    passed = len(failed_thresholds) == 0
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "case_count": len(case_reports),
        "sample_count": len(all_latency_samples),
        "iterations_per_case": normalized_iterations,
        "thresholds": active_thresholds,
        "aggregate": aggregate,
        "failed_thresholds": failed_thresholds,
        "passed": passed,
        "cases": case_reports,
    }
    return report, passed


def main() -> None:
    parser = argparse.ArgumentParser(description="Run deterministic API read-path latency benchmark")
    parser.add_argument(
        "--report-path",
        type=Path,
        default=DEFAULT_REPORT_PATH,
        help="Where to write the benchmark report JSON",
    )
    parser.add_argument(
        "--iterations",
        type=int,
        default=DEFAULT_ITERATIONS,
        help="Number of timed GET requests to run per read-path case",
    )
    parser.add_argument(
        "--threshold-read-path-p95-ms",
        type=float,
        default=DEFAULT_THRESHOLDS["read_path_p95_ms"],
        help="Maximum allowed aggregate read-path p95 latency in milliseconds",
    )
    parser.add_argument(
        "--threshold-read-path-success-rate",
        type=float,
        default=DEFAULT_THRESHOLDS["read_path_success_rate"],
        help="Minimum allowed read-path success rate",
    )
    args = parser.parse_args()

    report, passed = run_benchmark(
        thresholds={
            "read_path_p95_ms": float(args.threshold_read_path_p95_ms),
            "read_path_success_rate": float(args.threshold_read_path_success_rate),
        },
        iterations=max(1, int(args.iterations)),
    )
    args.report_path.parent.mkdir(parents=True, exist_ok=True)
    args.report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True))
    if not passed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
