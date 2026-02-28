#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT_DIR = Path(__file__).resolve().parents[3]
PLANNER_PATH = ROOT_DIR / "services" / "interview-engine" / "planner.py"
FOLLOWUP_SELECTOR_PATH = ROOT_DIR / "services" / "interview-engine" / "followup.py"
FIXTURE_DIR = ROOT_DIR / "tests" / "unit" / "fixtures" / "interview_relevance"
DEFAULT_REPORT_PATH = ROOT_DIR / ".tmp" / "interview-relevance-benchmark-report.json"

DEFAULT_THRESHOLDS = {
    "opening_coverage": 0.90,
    "followup_competency_alignment": 0.90,
    "followup_reason_alignment": 0.90,
    "non_repetition_rate": 0.80,
    "difficulty_bound_rate": 1.00,
    "overall_relevance": 0.90,
}

if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))


@dataclass(frozen=True)
class FollowupContext:
    last_question_index: int
    scores: dict[str, float]
    last_score: float
    expected_followup_competency: str
    expected_reasons: tuple[str, ...]
    expect_non_repeat: bool


@dataclass(frozen=True)
class BenchmarkCase:
    case_id: str
    session_id: str
    job_spec: dict[str, Any]
    candidate_profile: dict[str, Any]
    expected_opening_competencies: tuple[str, ...]
    followup_context: FollowupContext


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
        raw_followup = raw_case["followup_context"]

        case = BenchmarkCase(
            case_id=str(raw_case["case_id"]),
            session_id=str(raw_case.get("session_id", f"sess_benchmark_{raw_case['case_id']}")),
            job_spec=dict(raw_case["job_spec"]),
            candidate_profile=dict(raw_case["candidate_profile"]),
            expected_opening_competencies=tuple(str(value) for value in raw_case.get("expected_opening_competencies", [])),
            followup_context=FollowupContext(
                last_question_index=int(raw_followup.get("last_question_index", -1)),
                scores={str(key): float(value) for key, value in dict(raw_followup.get("scores", {})).items()},
                last_score=float(raw_followup["last_score"]),
                expected_followup_competency=str(raw_followup["expected_followup_competency"]),
                expected_reasons=tuple(str(value) for value in raw_followup.get("expected_reasons", [])),
                expect_non_repeat=bool(raw_followup.get("expect_non_repeat", False)),
            ),
        )
        cases.append(case)
    return cases


def _mean(values: list[float]) -> float:
    if not values:
        return 0.0
    return sum(values) / len(values)


def _clamp_question_index(raw_index: int, question_count: int) -> int:
    if question_count <= 0:
        return 0
    return max(0, min(question_count - 1, int(raw_index)))


def _opening_coverage(predicted: list[str], expected: tuple[str, ...]) -> float:
    expected_set = set(expected)
    if not expected_set:
        return 1.0
    predicted_set = set(predicted)
    return len(expected_set.intersection(predicted_set)) / len(expected_set)


def _opening_order_alignment(predicted: list[str], expected: tuple[str, ...]) -> float:
    if not expected:
        return 1.0
    span = min(len(predicted), len(expected))
    if span == 0:
        return 0.0
    matched = sum(1 for idx in range(span) if predicted[idx] == expected[idx])
    return matched / len(expected)


def run_benchmark(
    *,
    fixtures_dir: Path = FIXTURE_DIR,
    thresholds: dict[str, float] | None = None,
) -> tuple[dict[str, Any], bool]:
    active_thresholds = dict(DEFAULT_THRESHOLDS)
    if thresholds:
        active_thresholds.update(thresholds)

    planner_module = _load_module("interview_question_planner_benchmark", PLANNER_PATH)
    followup_module = _load_module("interview_followup_selector_benchmark", FOLLOWUP_SELECTOR_PATH)

    planner = planner_module.DeterministicQuestionPlanner()
    followup_selector = followup_module.AdaptiveFollowupSelector()
    cases = _load_benchmark_cases(fixtures_dir)

    case_reports: list[dict[str, Any]] = []
    opening_coverage_scores: list[float] = []
    opening_order_scores: list[float] = []
    followup_competency_scores: list[float] = []
    followup_reason_scores: list[float] = []
    non_repetition_scores: list[float] = []
    difficulty_bound_scores: list[float] = []

    for benchmark_case in cases:
        opening_questions = planner.plan_opening_questions(
            session_id=benchmark_case.session_id,
            job_spec=benchmark_case.job_spec,
            candidate_profile=benchmark_case.candidate_profile,
        )
        predicted_opening_competencies = [str(question.get("competency", "")) for question in opening_questions]

        coverage = _opening_coverage(predicted_opening_competencies, benchmark_case.expected_opening_competencies)
        opening_coverage_scores.append(coverage)

        order_alignment = _opening_order_alignment(predicted_opening_competencies, benchmark_case.expected_opening_competencies)
        opening_order_scores.append(order_alignment)

        last_index = _clamp_question_index(
            benchmark_case.followup_context.last_question_index,
            len(opening_questions),
        )
        last_question = opening_questions[last_index] if opening_questions else {}

        decision = followup_selector.select_followup(
            questions=opening_questions,
            scores=benchmark_case.followup_context.scores,
            last_question=last_question,
            last_score=benchmark_case.followup_context.last_score,
        )

        selected_competency = str(decision.get("competency", ""))
        selected_reason = str(decision.get("reason", ""))
        selected_difficulty = int(decision.get("difficulty", 1))
        last_competency = str(last_question.get("competency", "")) if isinstance(last_question, dict) else ""
        last_difficulty = int(last_question.get("difficulty", 1)) if isinstance(last_question, dict) else 1

        competency_match = selected_competency == benchmark_case.followup_context.expected_followup_competency
        followup_competency_scores.append(1.0 if competency_match else 0.0)

        expected_reasons = set(benchmark_case.followup_context.expected_reasons)
        reason_match = selected_reason in expected_reasons if expected_reasons else True
        followup_reason_scores.append(1.0 if reason_match else 0.0)

        non_repetition_pass = (
            selected_competency != last_competency
            if benchmark_case.followup_context.expect_non_repeat
            else True
        )
        non_repetition_scores.append(1.0 if non_repetition_pass else 0.0)

        difficulty_pass = 1 <= selected_difficulty <= 5 and selected_difficulty >= max(1, min(5, last_difficulty))
        difficulty_bound_scores.append(1.0 if difficulty_pass else 0.0)

        case_relevance = _mean(
            [
                coverage,
                order_alignment,
                1.0 if competency_match else 0.0,
                1.0 if reason_match else 0.0,
                1.0 if non_repetition_pass else 0.0,
                1.0 if difficulty_pass else 0.0,
            ]
        )

        case_reports.append(
            {
                "case_id": benchmark_case.case_id,
                "expected_opening_competencies": list(benchmark_case.expected_opening_competencies),
                "predicted_opening_competencies": predicted_opening_competencies,
                "opening_coverage": round(coverage, 3),
                "opening_order_alignment": round(order_alignment, 3),
                "followup_expected_competency": benchmark_case.followup_context.expected_followup_competency,
                "followup_selected_competency": selected_competency,
                "followup_competency_match": competency_match,
                "followup_expected_reasons": list(benchmark_case.followup_context.expected_reasons),
                "followup_selected_reason": selected_reason,
                "followup_reason_match": reason_match,
                "expect_non_repeat": benchmark_case.followup_context.expect_non_repeat,
                "followup_non_repetition_pass": non_repetition_pass,
                "followup_difficulty": selected_difficulty,
                "followup_difficulty_bound_pass": difficulty_pass,
                "followup_confidence": round(float(decision.get("confidence", 0.0)), 3),
                "case_relevance_score": round(case_relevance, 3),
            }
        )

    aggregate = {
        "opening_coverage": round(_mean(opening_coverage_scores), 3),
        "opening_order_alignment": round(_mean(opening_order_scores), 3),
        "followup_competency_alignment": round(_mean(followup_competency_scores), 3),
        "followup_reason_alignment": round(_mean(followup_reason_scores), 3),
        "non_repetition_rate": round(_mean(non_repetition_scores), 3),
        "difficulty_bound_rate": round(_mean(difficulty_bound_scores), 3),
    }
    aggregate["overall_relevance"] = round(
        (
            (aggregate["opening_coverage"] * 0.25)
            + (aggregate["opening_order_alignment"] * 0.15)
            + (aggregate["followup_competency_alignment"] * 0.25)
            + (aggregate["followup_reason_alignment"] * 0.15)
            + (aggregate["non_repetition_rate"] * 0.10)
            + (aggregate["difficulty_bound_rate"] * 0.10)
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
    parser = argparse.ArgumentParser(description="Run deterministic interview relevance benchmark quality gate.")
    parser.add_argument("--fixtures-dir", default=str(FIXTURE_DIR), help="Directory containing benchmark_*.json fixtures")
    parser.add_argument("--report-path", default=str(DEFAULT_REPORT_PATH), help="Path to write JSON benchmark report")
    parser.add_argument("--min-opening-coverage", type=float, default=DEFAULT_THRESHOLDS["opening_coverage"])
    parser.add_argument(
        "--min-followup-competency-alignment",
        type=float,
        default=DEFAULT_THRESHOLDS["followup_competency_alignment"],
    )
    parser.add_argument(
        "--min-followup-reason-alignment",
        type=float,
        default=DEFAULT_THRESHOLDS["followup_reason_alignment"],
    )
    parser.add_argument("--min-non-repetition-rate", type=float, default=DEFAULT_THRESHOLDS["non_repetition_rate"])
    parser.add_argument("--min-difficulty-bound-rate", type=float, default=DEFAULT_THRESHOLDS["difficulty_bound_rate"])
    parser.add_argument("--min-overall-relevance", type=float, default=DEFAULT_THRESHOLDS["overall_relevance"])
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    report, passed = run_benchmark(
        fixtures_dir=Path(args.fixtures_dir),
        thresholds={
            "opening_coverage": args.min_opening_coverage,
            "followup_competency_alignment": args.min_followup_competency_alignment,
            "followup_reason_alignment": args.min_followup_reason_alignment,
            "non_repetition_rate": args.min_non_repetition_rate,
            "difficulty_bound_rate": args.min_difficulty_bound_rate,
            "overall_relevance": args.min_overall_relevance,
        },
    )

    report_path = Path(args.report_path)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
