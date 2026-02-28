#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib
import importlib.util
import json
import sys
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any


ROOT_DIR = Path(__file__).resolve().parents[3]
API_GATEWAY_DIR = ROOT_DIR / "apps" / "api-gateway"
AGGREGATOR_PATH = ROOT_DIR / "services" / "progress-tracking" / "aggregator.py"
TRAJECTORY_PLANNER_PATH = ROOT_DIR / "services" / "trajectory-planning" / "generator.py"
VALIDATOR_PATH = ROOT_DIR / "services" / "quality-eval" / "schema_validation" / "validator.py"
FIXTURE_DIR = ROOT_DIR / "tests" / "unit" / "fixtures" / "trajectory_quality"
DEFAULT_REPORT_PATH = ROOT_DIR / ".tmp" / "trajectory-quality-benchmark-report.json"

DEFAULT_THRESHOLDS = {
    "trend_metric_alignment_rate": 1.0,
    "readiness_signal_alignment_rate": 1.0,
    "trajectory_dashboard_consistency_rate": 1.0,
    "trajectory_plan_structure_rate": 1.0,
    "dashboard_schema_valid_rate": 1.0,
    "overall_trajectory_quality": 1.0,
}

if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))
if str(API_GATEWAY_DIR) not in sys.path:
    sys.path.insert(0, str(API_GATEWAY_DIR))


@dataclass(frozen=True)
class BenchmarkCase:
    case_id: str
    candidate_id: str
    candidate_profile: dict[str, Any]
    target_role: str
    interview_sessions: list[dict[str, Any]]
    feedback_reports: list[dict[str, Any]]
    trajectory_context: dict[str, Any]
    expectations: dict[str, Any]
    reference_date: date | None


def _load_module(module_name: str, module_path: Path):
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load module: {module_path}")

    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _parse_reference_date(raw_value: Any) -> date | None:
    if not isinstance(raw_value, str) or not raw_value.strip():
        return None
    try:
        return date.fromisoformat(raw_value.strip())
    except ValueError:
        return None


def _load_benchmark_cases(fixtures_dir: Path) -> list[BenchmarkCase]:
    fixture_paths = sorted(fixtures_dir.glob("benchmark_*.json"))
    if not fixture_paths:
        raise RuntimeError(f"No benchmark fixtures found under {fixtures_dir}")

    cases: list[BenchmarkCase] = []
    for fixture_path in fixture_paths:
        raw_case = json.loads(fixture_path.read_text(encoding="utf-8"))
        cases.append(
            BenchmarkCase(
                case_id=str(raw_case["case_id"]),
                candidate_id=str(raw_case["candidate_id"]),
                candidate_profile=dict(raw_case.get("candidate_profile", {})),
                target_role=str(raw_case["target_role"]),
                interview_sessions=[entry for entry in raw_case.get("interview_sessions", []) if isinstance(entry, dict)],
                feedback_reports=[entry for entry in raw_case.get("feedback_reports", []) if isinstance(entry, dict)],
                trajectory_context=dict(raw_case.get("trajectory_context", {})),
                expectations=dict(raw_case.get("expectations", {})),
                reference_date=_parse_reference_date(raw_case.get("reference_date")),
            )
        )
    return cases


def _mean(values: list[float]) -> float:
    if not values:
        return 0.0
    return sum(values) / len(values)


def _score_match(actual: float | None, expected: Any, *, tolerance: float = 0.01) -> bool:
    if not isinstance(expected, (int, float)) or isinstance(expected, bool):
        return True
    if not isinstance(actual, (int, float)):
        return False
    return abs(float(actual) - float(expected)) <= tolerance


def _build_dashboard_payload(
    *,
    app_module: Any,
    candidate_id: str,
    progress_summary: dict[str, Any],
    latest_trajectory_plan: dict[str, Any] | None,
) -> dict[str, Any]:
    summary = progress_summary if isinstance(progress_summary, dict) else {}
    competency_trends = app_module._normalize_progress_competency_trends(summary.get("competency_trends"))
    latest_trajectory_metadata = app_module._latest_trajectory_plan_dashboard_metadata(latest_trajectory_plan)

    return {
        "candidate_id": candidate_id,
        "progress_summary": summary,
        "competency_trend_cards": {
            "top_improving": app_module._build_top_improving_competency_cards(competency_trends),
            "top_risk": app_module._build_top_risk_competency_cards(competency_trends),
        },
        "readiness_signals": app_module._build_dashboard_readiness_signals(
            progress_summary=summary,
            latest_trajectory_metadata=latest_trajectory_metadata,
        ),
        "latest_trajectory_plan": latest_trajectory_metadata,
    }


def _trajectory_plan_structure_pass(generated_plan: dict[str, Any]) -> bool:
    horizon_months = generated_plan.get("horizon_months")
    if not isinstance(horizon_months, int) or isinstance(horizon_months, bool) or not (1 <= horizon_months <= 24):
        return False

    readiness_score = generated_plan.get("role_readiness_score")
    if not isinstance(readiness_score, (int, float)) or isinstance(readiness_score, bool):
        return False
    if not (0.0 <= float(readiness_score) <= 100.0):
        return False

    milestones = generated_plan.get("milestones")
    if not isinstance(milestones, list) or len(milestones) < 3:
        return False
    milestone_dates: list[str] = []
    for milestone in milestones:
        if not isinstance(milestone, dict):
            return False
        name = str(milestone.get("name", "")).strip()
        metric = str(milestone.get("metric", "")).strip()
        target_date = str(milestone.get("target_date", "")).strip()
        if not name or not metric or not target_date:
            return False
        milestone_dates.append(target_date)
    if milestone_dates != sorted(milestone_dates):
        return False

    first_metric = str(milestones[0].get("metric", "")).lower()
    if "current=" not in first_metric or "target=" not in first_metric or "delta=" not in first_metric:
        return False

    weekly_plan = generated_plan.get("weekly_plan")
    if not isinstance(weekly_plan, list) or not (4 <= len(weekly_plan) <= 8):
        return False
    expected_weeks = list(range(1, len(weekly_plan) + 1))
    actual_weeks: list[int] = []
    for entry in weekly_plan:
        if not isinstance(entry, dict):
            return False
        week = entry.get("week")
        actions = entry.get("actions")
        if not isinstance(week, int) or isinstance(week, bool):
            return False
        if not isinstance(actions, list) or not actions:
            return False
        if any(not str(action).strip() for action in actions):
            return False
        actual_weeks.append(week)
    return actual_weeks == expected_weeks


def _trend_metric_alignment_pass(
    *,
    dashboard_payload: dict[str, Any],
    progress_summary: dict[str, Any],
    expectations: dict[str, Any],
) -> bool:
    cards = dashboard_payload.get("competency_trend_cards", {})
    top_improving = cards.get("top_improving") if isinstance(cards, dict) else []
    top_risk = cards.get("top_risk") if isinstance(cards, dict) else []

    improving_competencies = [str(item.get("competency", "")) for item in top_improving if isinstance(item, dict)]
    risk_competencies = [str(item.get("competency", "")) for item in top_risk if isinstance(item, dict)]

    expected_improving = [str(value) for value in expectations.get("top_improving_competencies", [])]
    expected_risk = [str(value) for value in expectations.get("top_risk_competencies", [])]

    if improving_competencies != expected_improving:
        return False
    if risk_competencies != expected_risk:
        return False

    expected_improving_directions = [str(value) for value in expectations.get("top_improving_directions", [])]
    if expected_improving_directions:
        improving_directions = [str(item.get("trend_direction", "")) for item in top_improving if isinstance(item, dict)]
        if improving_directions != expected_improving_directions:
            return False

    delta = progress_summary.get("delta")
    overall_delta = None
    if isinstance(delta, dict):
        raw_delta = delta.get("overall_score")
        if isinstance(raw_delta, (int, float)) and not isinstance(raw_delta, bool):
            overall_delta = round(float(raw_delta), 2)
    if not _score_match(overall_delta, expectations.get("overall_delta_score")):
        return False

    return True


def _readiness_signal_alignment_pass(
    *,
    dashboard_payload: dict[str, Any],
    expectations: dict[str, Any],
) -> bool:
    readiness = dashboard_payload.get("readiness_signals")
    if not isinstance(readiness, dict):
        return False

    expected_snapshot_count = expectations.get("snapshot_count")
    if isinstance(expected_snapshot_count, int) and readiness.get("snapshot_count") != expected_snapshot_count:
        return False

    expected_momentum = expectations.get("momentum")
    if isinstance(expected_momentum, str) and readiness.get("momentum") != expected_momentum:
        return False

    expected_band = expectations.get("readiness_band")
    if isinstance(expected_band, str) and readiness.get("readiness_band") != expected_band:
        return False

    overall_score = readiness.get("overall_score")
    if isinstance(overall_score, (int, float)) and isinstance(expectations.get("overall_score"), (int, float)):
        if not _score_match(float(overall_score), expectations.get("overall_score")):
            return False

    return True


def _trajectory_dashboard_consistency_pass(
    *,
    app_module: Any,
    dashboard_payload: dict[str, Any],
    latest_trajectory_plan: dict[str, Any] | None,
    expectations: dict[str, Any],
) -> bool:
    latest_metadata = dashboard_payload.get("latest_trajectory_plan")
    readiness = dashboard_payload.get("readiness_signals")
    if not isinstance(latest_metadata, dict) or not isinstance(readiness, dict):
        return False

    expected_available = bool(expectations.get("latest_trajectory_available", False))
    if bool(latest_metadata.get("available", False)) != expected_available:
        return False

    if expected_available:
        expected_plan_id = str(expectations.get("latest_trajectory_plan_id", "")).strip()
        expected_version = expectations.get("latest_trajectory_version")
        expected_supersedes = str(expectations.get("latest_trajectory_supersedes_trajectory_plan_id", "")).strip()

        if expected_plan_id and latest_metadata.get("trajectory_plan_id") != expected_plan_id:
            return False
        if isinstance(expected_version, int) and latest_metadata.get("version") != expected_version:
            return False
        if expected_supersedes and latest_metadata.get("supersedes_trajectory_plan_id") != expected_supersedes:
            return False

        trajectory_readiness_score = latest_metadata.get("role_readiness_score")
        if not isinstance(trajectory_readiness_score, (int, float)) or isinstance(trajectory_readiness_score, bool):
            return False
        readiness_score = readiness.get("trajectory_readiness_score")
        if not isinstance(readiness_score, (int, float)) or isinstance(readiness_score, bool):
            return False
        if not _score_match(float(readiness_score), float(trajectory_readiness_score)):
            return False

        expected_band = app_module._readiness_band_for_score(float(trajectory_readiness_score))
        if readiness.get("readiness_band") != expected_band:
            return False

        if not isinstance(latest_trajectory_plan, dict):
            return False
    else:
        if "trajectory_readiness_score" in readiness:
            return False
        current_score = readiness.get("overall_score")
        resolved_score = float(current_score) if isinstance(current_score, (int, float)) and not isinstance(current_score, bool) else None
        expected_band = app_module._readiness_band_for_score(resolved_score)
        if readiness.get("readiness_band") != expected_band:
            return False

    return True


def run_benchmark(
    *,
    fixtures_dir: Path = FIXTURE_DIR,
    thresholds: dict[str, float] | None = None,
) -> tuple[dict[str, Any], bool]:
    active_thresholds = dict(DEFAULT_THRESHOLDS)
    if thresholds:
        active_thresholds.update(thresholds)

    app_module = importlib.import_module("api_gateway.app")
    aggregator_module = _load_module("progress_tracking_aggregator_benchmark", AGGREGATOR_PATH)
    trajectory_module = _load_module("trajectory_planning_benchmark", TRAJECTORY_PLANNER_PATH)
    validator_module = _load_module("core_schema_validator_trajectory_quality_benchmark", VALIDATOR_PATH)

    aggregator = aggregator_module.LongitudinalProgressAggregator()
    planner = trajectory_module.DeterministicTrajectoryPlanner()
    validator = validator_module.CoreSchemaValidator.from_file()

    cases = _load_benchmark_cases(fixtures_dir)

    case_reports: list[dict[str, Any]] = []
    trend_alignment_scores: list[float] = []
    readiness_alignment_scores: list[float] = []
    trajectory_consistency_scores: list[float] = []
    plan_structure_scores: list[float] = []
    dashboard_schema_valid_scores: list[float] = []

    for benchmark_case in cases:
        progress_summary = aggregator.aggregate(
            interview_sessions=benchmark_case.interview_sessions,
            feedback_reports=benchmark_case.feedback_reports,
        )
        generated_plan = planner.generate(
            candidate_profile=benchmark_case.candidate_profile,
            target_role=benchmark_case.target_role,
            progress_summary=progress_summary,
            reference_date=benchmark_case.reference_date,
        )

        latest_trajectory_plan: dict[str, Any] | None = None
        include_latest = bool(benchmark_case.trajectory_context.get("include_latest", False))
        if include_latest:
            latest_trajectory_plan = {
                "trajectory_plan_id": str(
                    benchmark_case.trajectory_context.get("trajectory_plan_id", f"tp_{benchmark_case.case_id}_latest")
                ),
                "candidate_id": benchmark_case.candidate_id,
                "target_role": benchmark_case.target_role,
                "version": int(benchmark_case.trajectory_context.get("version", 1)),
                "generated_at": str(
                    benchmark_case.trajectory_context.get(
                        "generated_at",
                        "2026-02-28T00:00:00Z",
                    )
                ),
                "horizon_months": int(generated_plan.get("horizon_months", 3)),
                "role_readiness_score": float(generated_plan.get("role_readiness_score", 0.0)),
            }
            supersedes_id = benchmark_case.trajectory_context.get("supersedes_trajectory_plan_id")
            if isinstance(supersedes_id, str) and supersedes_id.strip():
                latest_trajectory_plan["supersedes_trajectory_plan_id"] = supersedes_id.strip()

        dashboard_payload = _build_dashboard_payload(
            app_module=app_module,
            candidate_id=benchmark_case.candidate_id,
            progress_summary=progress_summary,
            latest_trajectory_plan=latest_trajectory_plan,
        )
        dashboard_validation = validator.validate("CandidateProgressDashboard", dashboard_payload)

        trend_alignment_pass = _trend_metric_alignment_pass(
            dashboard_payload=dashboard_payload,
            progress_summary=progress_summary,
            expectations=benchmark_case.expectations,
        )
        readiness_alignment_pass = _readiness_signal_alignment_pass(
            dashboard_payload=dashboard_payload,
            expectations=benchmark_case.expectations,
        )
        trajectory_consistency_pass = _trajectory_dashboard_consistency_pass(
            app_module=app_module,
            dashboard_payload=dashboard_payload,
            latest_trajectory_plan=latest_trajectory_plan,
            expectations=benchmark_case.expectations,
        )
        plan_structure_pass = _trajectory_plan_structure_pass(generated_plan)
        dashboard_schema_valid = dashboard_validation.is_valid

        trend_alignment_scores.append(1.0 if trend_alignment_pass else 0.0)
        readiness_alignment_scores.append(1.0 if readiness_alignment_pass else 0.0)
        trajectory_consistency_scores.append(1.0 if trajectory_consistency_pass else 0.0)
        plan_structure_scores.append(1.0 if plan_structure_pass else 0.0)
        dashboard_schema_valid_scores.append(1.0 if dashboard_schema_valid else 0.0)

        case_quality_score = _mean(
            [
                1.0 if trend_alignment_pass else 0.0,
                1.0 if readiness_alignment_pass else 0.0,
                1.0 if trajectory_consistency_pass else 0.0,
                1.0 if plan_structure_pass else 0.0,
                1.0 if dashboard_schema_valid else 0.0,
            ]
        )

        case_reports.append(
            {
                "case_id": benchmark_case.case_id,
                "candidate_id": benchmark_case.candidate_id,
                "target_role": benchmark_case.target_role,
                "history_counts": progress_summary.get("history_counts", {}),
                "generated_trajectory_plan": generated_plan,
                "dashboard_payload": dashboard_payload,
                "dashboard_schema_valid": dashboard_schema_valid,
                "dashboard_schema_issues": [
                    {"path": issue.path, "message": issue.message}
                    for issue in dashboard_validation.issues
                ],
                "trend_metric_alignment_pass": trend_alignment_pass,
                "readiness_signal_alignment_pass": readiness_alignment_pass,
                "trajectory_dashboard_consistency_pass": trajectory_consistency_pass,
                "trajectory_plan_structure_pass": plan_structure_pass,
                "case_quality_score": round(case_quality_score, 3),
            }
        )

    aggregate = {
        "trend_metric_alignment_rate": round(_mean(trend_alignment_scores), 3),
        "readiness_signal_alignment_rate": round(_mean(readiness_alignment_scores), 3),
        "trajectory_dashboard_consistency_rate": round(_mean(trajectory_consistency_scores), 3),
        "trajectory_plan_structure_rate": round(_mean(plan_structure_scores), 3),
        "dashboard_schema_valid_rate": round(_mean(dashboard_schema_valid_scores), 3),
    }
    aggregate["overall_trajectory_quality"] = round(
        _mean(
            [
                aggregate["trend_metric_alignment_rate"],
                aggregate["readiness_signal_alignment_rate"],
                aggregate["trajectory_dashboard_consistency_rate"],
                aggregate["trajectory_plan_structure_rate"],
                aggregate["dashboard_schema_valid_rate"],
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
        "cases": case_reports,
    }
    return report, passed


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run deterministic trajectory quality benchmark threshold gate.")
    parser.add_argument("--fixtures-dir", default=str(FIXTURE_DIR), help="Directory containing benchmark_*.json fixtures")
    parser.add_argument("--report-path", default=str(DEFAULT_REPORT_PATH), help="Path to write JSON benchmark report")
    parser.add_argument(
        "--min-trend-metric-alignment-rate",
        type=float,
        default=DEFAULT_THRESHOLDS["trend_metric_alignment_rate"],
    )
    parser.add_argument(
        "--min-readiness-signal-alignment-rate",
        type=float,
        default=DEFAULT_THRESHOLDS["readiness_signal_alignment_rate"],
    )
    parser.add_argument(
        "--min-trajectory-dashboard-consistency-rate",
        type=float,
        default=DEFAULT_THRESHOLDS["trajectory_dashboard_consistency_rate"],
    )
    parser.add_argument(
        "--min-trajectory-plan-structure-rate",
        type=float,
        default=DEFAULT_THRESHOLDS["trajectory_plan_structure_rate"],
    )
    parser.add_argument(
        "--min-dashboard-schema-valid-rate",
        type=float,
        default=DEFAULT_THRESHOLDS["dashboard_schema_valid_rate"],
    )
    parser.add_argument(
        "--min-overall-trajectory-quality",
        type=float,
        default=DEFAULT_THRESHOLDS["overall_trajectory_quality"],
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    report, passed = run_benchmark(
        fixtures_dir=Path(args.fixtures_dir),
        thresholds={
            "trend_metric_alignment_rate": args.min_trend_metric_alignment_rate,
            "readiness_signal_alignment_rate": args.min_readiness_signal_alignment_rate,
            "trajectory_dashboard_consistency_rate": args.min_trajectory_dashboard_consistency_rate,
            "trajectory_plan_structure_rate": args.min_trajectory_plan_structure_rate,
            "dashboard_schema_valid_rate": args.min_dashboard_schema_valid_rate,
            "overall_trajectory_quality": args.min_overall_trajectory_quality,
        },
    )

    report_path = Path(args.report_path)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
