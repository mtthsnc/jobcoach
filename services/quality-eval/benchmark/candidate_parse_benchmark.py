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
PARSER_PATH = ROOT_DIR / "services" / "candidate-profile" / "parser.py"
STORYBANK_PATH = ROOT_DIR / "services" / "candidate-profile" / "storybank.py"
VALIDATOR_PATH = ROOT_DIR / "services" / "quality-eval" / "schema_validation" / "validator.py"
FIXTURE_DIR = ROOT_DIR / "tests" / "unit" / "fixtures" / "candidate_parsing"
DEFAULT_REPORT_PATH = ROOT_DIR / ".tmp" / "candidate-parse-benchmark-report.json"

DEFAULT_THRESHOLDS = {
    "candidate_profile_valid_rate": 0.95,
    "required_field_coverage": 0.90,
    "story_quality_p50": 0.70,
    "story_quality_p10": 0.65,
}

if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))


@dataclass(frozen=True)
class BenchmarkCase:
    case_id: str
    input_payload: dict[str, Any]
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
        case = BenchmarkCase(
            case_id=str(raw_case["case_id"]),
            input_payload=dict(raw_case["input"]),
            expectations=dict(raw_case.get("expectations", {})),
        )
        cases.append(case)
    return cases


def _evaluate_required_fields(profile: dict[str, Any], expectations: dict[str, Any]) -> tuple[list[dict[str, Any]], float]:
    checks: list[dict[str, Any]] = []

    if "candidate_id" in expectations:
        expected = str(expectations["candidate_id"])
        actual = str(profile.get("candidate_id", ""))
        checks.append(
            {
                "field": "candidate_id",
                "expected": expected,
                "actual": actual,
                "passed": actual == expected,
            }
        )

    if "summary" in expectations:
        expected = str(expectations["summary"])
        actual = str(profile.get("summary", ""))
        checks.append(
            {
                "field": "summary",
                "expected": expected,
                "actual": actual,
                "passed": actual == expected,
            }
        )

    if "experience_min_items" in expectations:
        expected = int(expectations["experience_min_items"])
        actual = len(profile.get("experience", []))
        checks.append(
            {
                "field": "experience",
                "expected_min_items": expected,
                "actual_items": actual,
                "passed": actual >= expected,
            }
        )

    for required_skill in expectations.get("required_skill_keys", []):
        skill_key = str(required_skill)
        skill_exists = skill_key in profile.get("skills", {})
        checks.append(
            {
                "field": f"skills.{skill_key}",
                "expected": "present",
                "actual": "present" if skill_exists else "missing",
                "passed": skill_exists,
            }
        )

    if not checks:
        return checks, 1.0

    passed_count = sum(1 for check in checks if bool(check["passed"]))
    return checks, passed_count / len(checks)


def _mean(values: list[float]) -> float:
    if not values:
        return 0.0
    return sum(values) / len(values)


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


def run_benchmark(
    *,
    fixtures_dir: Path = FIXTURE_DIR,
    thresholds: dict[str, float] | None = None,
) -> tuple[dict[str, Any], bool]:
    active_thresholds = dict(DEFAULT_THRESHOLDS)
    if thresholds:
        active_thresholds.update(thresholds)

    parser_module = _load_module("candidate_profile_parser_benchmark", PARSER_PATH)
    storybank_module = _load_module("candidate_storybank_generator_benchmark", STORYBANK_PATH)
    validator_module = _load_module("core_schema_validator_candidate_benchmark", VALIDATOR_PATH)

    parser = parser_module.CandidateProfileParser()
    storybank_generator = storybank_module.CandidateStorybankGenerator()
    validator = validator_module.CoreSchemaValidator.from_file()

    cases = _load_benchmark_cases(fixtures_dir)
    case_reports: list[dict[str, Any]] = []
    candidate_profile_valid_scores: list[float] = []
    required_field_coverages: list[float] = []
    story_quality_scores_all: list[float] = []

    for benchmark_case in cases:
        profile = parser.parse(**benchmark_case.input_payload)
        stories = storybank_generator.generate(
            candidate_id=profile["candidate_id"],
            experiences=list(profile.get("experience", [])),
            story_notes=benchmark_case.input_payload.get("story_notes"),
        )

        profile_with_storybank = dict(profile)
        if stories:
            profile_with_storybank["storybank"] = stories

        validation = validator.validate("CandidateProfile", profile_with_storybank)
        candidate_profile_valid = validation.is_valid
        candidate_profile_valid_scores.append(1.0 if candidate_profile_valid else 0.0)

        required_field_checks, required_field_coverage = _evaluate_required_fields(profile, benchmark_case.expectations)
        required_field_coverages.append(required_field_coverage)

        story_quality_scores = [float(story.get("evidence_quality", 0.0)) for story in stories]
        story_quality_scores_all.extend(story_quality_scores)

        case_reports.append(
            {
                "case_id": benchmark_case.case_id,
                "candidate_id": profile.get("candidate_id"),
                "parse_confidence": profile.get("parse_confidence"),
                "candidate_profile_valid": candidate_profile_valid,
                "candidate_profile_validation_issues": [
                    {"path": issue.path, "message": issue.message}
                    for issue in validation.issues
                ],
                "required_field_checks": required_field_checks,
                "required_field_coverage": round(required_field_coverage, 3),
                "story_count": len(stories),
                "story_quality_scores": [round(value, 3) for value in story_quality_scores],
                "story_quality_mean": round(_mean(story_quality_scores), 3),
            }
        )

    story_quality_distribution = {
        "count": len(story_quality_scores_all),
        "min": round(min(story_quality_scores_all), 3) if story_quality_scores_all else 0.0,
        "p10": round(_percentile(story_quality_scores_all, 0.10), 3),
        "p50": round(_percentile(story_quality_scores_all, 0.50), 3),
        "p90": round(_percentile(story_quality_scores_all, 0.90), 3),
        "max": round(max(story_quality_scores_all), 3) if story_quality_scores_all else 0.0,
        "mean": round(_mean(story_quality_scores_all), 3),
    }

    aggregate = {
        "candidate_profile_valid_rate": round(_mean(candidate_profile_valid_scores), 3),
        "required_field_coverage": round(_mean(required_field_coverages), 3),
        "story_quality_p10": story_quality_distribution["p10"],
        "story_quality_p50": story_quality_distribution["p50"],
    }

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
        "story_quality_distribution": story_quality_distribution,
        "failed_thresholds": failed_thresholds,
        "passed": passed,
        "cases": case_reports,
    }
    return report, passed


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run deterministic candidate parse benchmark quality gate.")
    parser.add_argument("--fixtures-dir", default=str(FIXTURE_DIR), help="Directory containing benchmark_*.json fixtures")
    parser.add_argument("--report-path", default=str(DEFAULT_REPORT_PATH), help="Path to write JSON benchmark report")
    parser.add_argument(
        "--min-candidate-profile-valid-rate",
        type=float,
        default=DEFAULT_THRESHOLDS["candidate_profile_valid_rate"],
    )
    parser.add_argument(
        "--min-required-field-coverage",
        type=float,
        default=DEFAULT_THRESHOLDS["required_field_coverage"],
    )
    parser.add_argument(
        "--min-story-quality-p50",
        type=float,
        default=DEFAULT_THRESHOLDS["story_quality_p50"],
    )
    parser.add_argument(
        "--min-story-quality-p10",
        type=float,
        default=DEFAULT_THRESHOLDS["story_quality_p10"],
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    report, passed = run_benchmark(
        fixtures_dir=Path(args.fixtures_dir),
        thresholds={
            "candidate_profile_valid_rate": args.min_candidate_profile_valid_rate,
            "required_field_coverage": args.min_required_field_coverage,
            "story_quality_p50": args.min_story_quality_p50,
            "story_quality_p10": args.min_story_quality_p10,
        },
    )

    report_path = Path(args.report_path)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
