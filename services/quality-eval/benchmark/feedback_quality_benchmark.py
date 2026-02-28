#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.util
import importlib
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT_DIR = Path(__file__).resolve().parents[3]
API_GATEWAY_DIR = ROOT_DIR / "apps" / "api-gateway"
FIXTURE_DIR = ROOT_DIR / "tests" / "unit" / "fixtures" / "feedback_quality"
DEFAULT_REPORT_PATH = ROOT_DIR / ".tmp" / "feedback-quality-benchmark-report.json"

DEFAULT_THRESHOLDS = {
    "completeness_rate": 0.95,
    "root_cause_alignment_rate": 0.85,
    "evidence_traceability_rate": 0.95,
    "rewrite_structure_rate": 0.95,
    "action_plan_coverage_rate": 1.00,
    "overall_feedback_quality": 0.90,
}

if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))
if str(API_GATEWAY_DIR) not in sys.path:
    sys.path.insert(0, str(API_GATEWAY_DIR))


@dataclass(frozen=True)
class BenchmarkCase:
    case_id: str
    session: dict[str, Any]
    expectations: dict[str, Any]


def _load_module(module_name: str, module_path: Path):
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load module: {module_path}")

    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


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
                session=dict(raw_case["session"]),
                expectations=dict(raw_case.get("expectations", {})),
            )
        )
    return cases


def _mean(values: list[float]) -> float:
    if not values:
        return 0.0
    return sum(values) / len(values)


def _has_star_structure(text: str) -> bool:
    lowered = text.lower()
    return all(token in lowered for token in ("situation:", "task:", "action:", "result:"))


def run_benchmark(
    *,
    fixtures_dir: Path = FIXTURE_DIR,
    thresholds: dict[str, float] | None = None,
) -> tuple[dict[str, Any], bool]:
    active_thresholds = dict(DEFAULT_THRESHOLDS)
    if thresholds:
        active_thresholds.update(thresholds)

    app_module = importlib.import_module("api_gateway.app")
    cases = _load_benchmark_cases(fixtures_dir)

    case_reports: list[dict[str, Any]] = []
    completeness_scores: list[float] = []
    root_cause_alignment_scores: list[float] = []
    evidence_traceability_scores: list[float] = []
    rewrite_structure_scores: list[float] = []
    action_plan_coverage_scores: list[float] = []

    for benchmark_case in cases:
        competency_scores, overall_score = app_module._aggregate_feedback_scores(benchmark_case.session)
        top_gaps = app_module._feedback_top_gaps(session=benchmark_case.session, competency_scores=competency_scores)
        action_plan = app_module._feedback_action_plan(top_gaps)
        answer_rewrites = app_module._feedback_answer_rewrites(session=benchmark_case.session, top_gaps=top_gaps)

        min_top_gaps = int(benchmark_case.expectations.get("min_top_gaps", 1))
        completeness_pass = (
            0.0 <= float(overall_score) <= 100.0
            and len(top_gaps) >= min_top_gaps
            and len(answer_rewrites) >= 1
            and len(action_plan) == 30
        )
        completeness_scores.append(1.0 if completeness_pass else 0.0)

        first_gap = top_gaps[0] if top_gaps else {}
        expected_first_severity = benchmark_case.expectations.get("expected_first_severity")
        expected_root_cause_fragments = [
            str(value).lower() for value in benchmark_case.expectations.get("expected_root_cause_contains", [])
        ]
        first_root_cause = str(first_gap.get("root_cause", "")).lower()
        severity_pass = True
        if isinstance(expected_first_severity, str) and expected_first_severity.strip():
            severity_pass = str(first_gap.get("severity", "")).strip() == expected_first_severity.strip()
        root_cause_fragments_pass = True
        if expected_root_cause_fragments:
            root_cause_fragments_pass = all(fragment in first_root_cause for fragment in expected_root_cause_fragments)
        root_cause_alignment_pass = severity_pass and root_cause_fragments_pass and bool(first_root_cause.strip())
        root_cause_alignment_scores.append(1.0 if root_cause_alignment_pass else 0.0)

        evidence_traceability_pass = all(
            (
                isinstance(gap, dict)
                and str(gap.get("evidence", "")).strip()
                and (
                    "score=" in str(gap.get("evidence", ""))
                    or "No response evidence captured" in str(gap.get("evidence", ""))
                )
            )
            for gap in top_gaps
        )
        evidence_traceability_scores.append(1.0 if evidence_traceability_pass else 0.0)

        rewrite_structure_pass = all(_has_star_structure(str(item)) for item in answer_rewrites)
        rewrite_structure_scores.append(1.0 if rewrite_structure_pass else 0.0)

        action_plan_days = [int(item.get("day", 0)) for item in action_plan if isinstance(item, dict)]
        action_plan_coverage_pass = action_plan_days == list(range(1, 31)) and all(
            str(item.get("task", "")).strip() and str(item.get("success_metric", "")).strip()
            for item in action_plan
            if isinstance(item, dict)
        )
        action_plan_coverage_scores.append(1.0 if action_plan_coverage_pass else 0.0)

        case_quality_score = _mean(
            [
                1.0 if completeness_pass else 0.0,
                1.0 if root_cause_alignment_pass else 0.0,
                1.0 if evidence_traceability_pass else 0.0,
                1.0 if rewrite_structure_pass else 0.0,
                1.0 if action_plan_coverage_pass else 0.0,
            ]
        )

        case_reports.append(
            {
                "case_id": benchmark_case.case_id,
                "overall_score": round(float(overall_score), 2),
                "competency_scores": competency_scores,
                "top_gaps": top_gaps,
                "answer_rewrites": answer_rewrites,
                "action_plan_count": len(action_plan),
                "completeness_pass": completeness_pass,
                "root_cause_alignment_pass": root_cause_alignment_pass,
                "evidence_traceability_pass": evidence_traceability_pass,
                "rewrite_structure_pass": rewrite_structure_pass,
                "action_plan_coverage_pass": action_plan_coverage_pass,
                "case_quality_score": round(case_quality_score, 3),
            }
        )

    aggregate = {
        "completeness_rate": round(_mean(completeness_scores), 3),
        "root_cause_alignment_rate": round(_mean(root_cause_alignment_scores), 3),
        "evidence_traceability_rate": round(_mean(evidence_traceability_scores), 3),
        "rewrite_structure_rate": round(_mean(rewrite_structure_scores), 3),
        "action_plan_coverage_rate": round(_mean(action_plan_coverage_scores), 3),
    }
    aggregate["overall_feedback_quality"] = round(
        _mean(
            [
                aggregate["completeness_rate"],
                aggregate["root_cause_alignment_rate"],
                aggregate["evidence_traceability_rate"],
                aggregate["rewrite_structure_rate"],
                aggregate["action_plan_coverage_rate"],
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
    parser = argparse.ArgumentParser(description="Run deterministic feedback quality benchmark threshold gate.")
    parser.add_argument("--fixtures-dir", default=str(FIXTURE_DIR), help="Directory containing benchmark_*.json fixtures")
    parser.add_argument("--report-path", default=str(DEFAULT_REPORT_PATH), help="Path to write JSON benchmark report")
    parser.add_argument("--min-completeness-rate", type=float, default=DEFAULT_THRESHOLDS["completeness_rate"])
    parser.add_argument(
        "--min-root-cause-alignment-rate",
        type=float,
        default=DEFAULT_THRESHOLDS["root_cause_alignment_rate"],
    )
    parser.add_argument(
        "--min-evidence-traceability-rate",
        type=float,
        default=DEFAULT_THRESHOLDS["evidence_traceability_rate"],
    )
    parser.add_argument(
        "--min-rewrite-structure-rate",
        type=float,
        default=DEFAULT_THRESHOLDS["rewrite_structure_rate"],
    )
    parser.add_argument(
        "--min-action-plan-coverage-rate",
        type=float,
        default=DEFAULT_THRESHOLDS["action_plan_coverage_rate"],
    )
    parser.add_argument(
        "--min-overall-feedback-quality",
        type=float,
        default=DEFAULT_THRESHOLDS["overall_feedback_quality"],
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    report, passed = run_benchmark(
        fixtures_dir=Path(args.fixtures_dir),
        thresholds={
            "completeness_rate": args.min_completeness_rate,
            "root_cause_alignment_rate": args.min_root_cause_alignment_rate,
            "evidence_traceability_rate": args.min_evidence_traceability_rate,
            "rewrite_structure_rate": args.min_rewrite_structure_rate,
            "action_plan_coverage_rate": args.min_action_plan_coverage_rate,
            "overall_feedback_quality": args.min_overall_feedback_quality,
        },
    )

    report_path = Path(args.report_path)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
