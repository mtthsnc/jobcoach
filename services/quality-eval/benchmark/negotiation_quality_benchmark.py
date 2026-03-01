#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib
import importlib.util
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


ROOT_DIR = Path(__file__).resolve().parents[3]
API_GATEWAY_DIR = ROOT_DIR / "apps" / "api-gateway"
NEGOTIATION_AGGREGATOR_PATH = ROOT_DIR / "services" / "negotiation-planning" / "aggregator.py"
NEGOTIATION_STRATEGY_PATH = ROOT_DIR / "services" / "negotiation-planning" / "generator.py"
NEGOTIATION_FOLLOWUP_PATH = ROOT_DIR / "services" / "negotiation-planning" / "followup.py"
VALIDATOR_PATH = ROOT_DIR / "services" / "quality-eval" / "schema_validation" / "validator.py"
FIXTURE_DIR = ROOT_DIR / "tests" / "unit" / "fixtures" / "negotiation_quality"
DEFAULT_REPORT_PATH = ROOT_DIR / ".tmp" / "negotiation-quality-benchmark-report.json"

DEFAULT_THRESHOLDS = {
    "strategy_structure_quality_rate": 1.0,
    "follow_up_cadence_quality_rate": 1.0,
    "branch_action_boundedness_rate": 1.0,
    "evidence_link_consistency_rate": 1.0,
    "negotiation_plan_schema_valid_rate": 1.0,
    "overall_negotiation_quality": 1.0,
}

if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))
if str(API_GATEWAY_DIR) not in sys.path:
    sys.path.insert(0, str(API_GATEWAY_DIR))


@dataclass(frozen=True)
class BenchmarkCase:
    case_id: str
    candidate_id: str
    target_role: str
    request_payload: dict[str, Any]
    candidate_profile: dict[str, Any]
    interview_sessions: list[dict[str, Any]]
    feedback_reports: list[dict[str, Any]]
    latest_trajectory_plan: dict[str, Any] | None
    offer_deadline_days_from_now: int | None
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
        raw_days = raw_case.get("offer_deadline_days_from_now")
        offer_deadline_days_from_now = None
        if isinstance(raw_days, int) and not isinstance(raw_days, bool):
            offer_deadline_days_from_now = int(raw_days)

        cases.append(
            BenchmarkCase(
                case_id=str(raw_case["case_id"]),
                candidate_id=str(raw_case["candidate_id"]),
                target_role=str(raw_case["target_role"]),
                request_payload=dict(raw_case.get("request_payload", {})),
                candidate_profile=dict(raw_case.get("candidate_profile", {})),
                interview_sessions=[entry for entry in raw_case.get("interview_sessions", []) if isinstance(entry, dict)],
                feedback_reports=[entry for entry in raw_case.get("feedback_reports", []) if isinstance(entry, dict)],
                latest_trajectory_plan=(
                    dict(raw_case["latest_trajectory_plan"])
                    if isinstance(raw_case.get("latest_trajectory_plan"), dict)
                    else None
                ),
                offer_deadline_days_from_now=offer_deadline_days_from_now,
                expectations=dict(raw_case.get("expectations", {})),
            )
        )

    return cases


def _mean(values: list[float]) -> float:
    if not values:
        return 0.0
    return sum(values) / len(values)


def _non_empty_text(raw_value: Any) -> bool:
    return isinstance(raw_value, str) and bool(raw_value.strip())


def _resolve_request_payload(case: BenchmarkCase) -> dict[str, Any]:
    payload = dict(case.request_payload)
    if case.offer_deadline_days_from_now is not None:
        deadline = (datetime.now(timezone.utc).date() + timedelta(days=case.offer_deadline_days_from_now)).isoformat()
        payload["offer_deadline_date"] = deadline
    return payload


def _strategy_structure_quality(
    payload: dict[str, Any],
    expectations: dict[str, Any],
) -> tuple[bool, dict[str, Any]]:
    strategy_summary = payload.get("strategy_summary")
    anchor_band = payload.get("anchor_band")
    concession_ladder = payload.get("concession_ladder")
    objection_playbook = payload.get("objection_playbook")
    talking_points = payload.get("talking_points")
    leverage_signals = payload.get("leverage_signals")
    risk_signals = payload.get("risk_signals")

    summary_pass = _non_empty_text(strategy_summary)

    anchor_order_pass = False
    if isinstance(anchor_band, dict):
        floor = anchor_band.get("floor_base_salary")
        target = anchor_band.get("target_base_salary")
        ceiling = anchor_band.get("ceiling_base_salary")
        anchor_order_pass = (
            isinstance(floor, int)
            and not isinstance(floor, bool)
            and isinstance(target, int)
            and not isinstance(target, bool)
            and isinstance(ceiling, int)
            and not isinstance(ceiling, bool)
            and floor <= target <= ceiling
            and _non_empty_text(anchor_band.get("currency"))
            and _non_empty_text(anchor_band.get("rationale"))
        )

    concession_structure_pass = False
    if isinstance(concession_ladder, list) and concession_ladder:
        steps = [item.get("step") for item in concession_ladder if isinstance(item, dict)]
        asks = [item.get("ask_base_salary") for item in concession_ladder if isinstance(item, dict)]
        step_sequence_pass = steps == list(range(1, len(steps) + 1))
        ask_bounds_pass = all(
            isinstance(ask, int) and not isinstance(ask, bool)
            for ask in asks
        ) and asks == sorted(asks, reverse=True)
        text_fields_pass = all(
            isinstance(item, dict)
            and _non_empty_text(item.get("trigger"))
            and _non_empty_text(item.get("concession"))
            and _non_empty_text(item.get("exchange_for"))
            and _non_empty_text(item.get("evidence"))
            for item in concession_ladder
        )
        concession_structure_pass = step_sequence_pass and ask_bounds_pass and text_fields_pass and len(concession_ladder) >= 2

    playbook_structure_pass = False
    if isinstance(objection_playbook, list) and objection_playbook:
        playbook_structure_pass = len(objection_playbook) >= 2 and all(
            isinstance(item, dict)
            and _non_empty_text(item.get("risk_signal"))
            and _non_empty_text(item.get("objection"))
            and _non_empty_text(item.get("response"))
            and _non_empty_text(item.get("evidence"))
            and _non_empty_text(item.get("fallback_trade"))
            for item in objection_playbook
        )

    talking_points_pass = isinstance(talking_points, list) and len(talking_points) >= 3 and all(
        _non_empty_text(point) for point in talking_points
    )

    expected_top_leverage = str(expectations.get("top_leverage_signal", "")).strip()
    top_leverage_pass = True
    if expected_top_leverage:
        top_leverage_pass = (
            isinstance(leverage_signals, list)
            and bool(leverage_signals)
            and isinstance(leverage_signals[0], dict)
            and str(leverage_signals[0].get("signal", "")) == expected_top_leverage
        )

    expected_top_risk = str(expectations.get("top_risk_signal", "")).strip()
    top_risk_pass = True
    if expected_top_risk:
        top_risk_pass = (
            isinstance(risk_signals, list)
            and bool(risk_signals)
            and isinstance(risk_signals[0], dict)
            and str(risk_signals[0].get("signal", "")) == expected_top_risk
        )

    passed = all(
        [
            summary_pass,
            anchor_order_pass,
            concession_structure_pass,
            playbook_structure_pass,
            talking_points_pass,
            top_leverage_pass,
            top_risk_pass,
        ]
    )
    return (
        passed,
        {
            "summary_pass": summary_pass,
            "anchor_order_pass": anchor_order_pass,
            "concession_structure_pass": concession_structure_pass,
            "playbook_structure_pass": playbook_structure_pass,
            "talking_points_pass": talking_points_pass,
            "top_leverage_pass": top_leverage_pass,
            "top_risk_pass": top_risk_pass,
        },
    )


def _follow_up_cadence_quality(
    payload: dict[str, Any],
    expectations: dict[str, Any],
) -> tuple[bool, dict[str, Any]]:
    follow_up_plan = payload.get("follow_up_plan")
    if not isinstance(follow_up_plan, dict):
        return False, {"follow_up_plan_present": False}

    thank_you_note = follow_up_plan.get("thank_you_note")
    cadence = follow_up_plan.get("recruiter_cadence")

    thank_you_pass = False
    if isinstance(thank_you_note, dict):
        send_by = thank_you_note.get("send_by_day_offset")
        key_points = thank_you_note.get("key_points")
        thank_you_pass = (
            isinstance(send_by, int)
            and not isinstance(send_by, bool)
            and 0 <= send_by <= 14
            and _non_empty_text(thank_you_note.get("subject"))
            and _non_empty_text(thank_you_note.get("body"))
            and isinstance(key_points, list)
            and len(key_points) >= 3
            and all(_non_empty_text(item) for item in key_points)
        )

    cadence_shape_pass = False
    cadence_offsets: list[int] = []
    if isinstance(cadence, list) and cadence:
        cadence_offsets = [
            int(item.get("day_offset"))
            for item in cadence
            if isinstance(item, dict)
            and isinstance(item.get("day_offset"), int)
            and not isinstance(item.get("day_offset"), bool)
        ]
        cadence_shape_pass = (
            len(cadence_offsets) == len(cadence)
            and cadence_offsets == sorted(cadence_offsets)
            and all(
                isinstance(item, dict)
                and item.get("channel") in {"email", "phone", "linkedin"}
                and _non_empty_text(item.get("objective"))
                and _non_empty_text(item.get("message"))
                for item in cadence
            )
        )

    expected_offsets = expectations.get("cadence_offsets")
    expected_offsets_pass = True
    if isinstance(expected_offsets, list) and expected_offsets:
        expected_offsets_pass = cadence_offsets == [int(value) for value in expected_offsets]

    passed = thank_you_pass and cadence_shape_pass and expected_offsets_pass
    return (
        passed,
        {
            "thank_you_pass": thank_you_pass,
            "cadence_shape_pass": cadence_shape_pass,
            "expected_offsets_pass": expected_offsets_pass,
            "cadence_offsets": cadence_offsets,
        },
    )


def _branch_action_boundedness(
    payload: dict[str, Any],
    expectations: dict[str, Any],
) -> tuple[bool, dict[str, Any]]:
    follow_up_plan = payload.get("follow_up_plan")
    follow_up_actions = payload.get("follow_up_actions")

    if not isinstance(follow_up_plan, dict):
        return False, {"follow_up_plan_present": False}

    branches = follow_up_plan.get("outcome_branches")
    branch_order_pass = False
    branch_actions_pass = False
    max_branch_action_day_offset = 0

    if isinstance(branches, list) and branches:
        expected_branch_order = expectations.get("branch_order")
        actual_order = [str(item.get("outcome", "")) for item in branches if isinstance(item, dict)]
        if isinstance(expected_branch_order, list) and expected_branch_order:
            branch_order_pass = actual_order == [str(value) for value in expected_branch_order]
        else:
            branch_order_pass = True

        branch_action_offsets: list[int] = []
        branch_actions_pass = all(
            isinstance(branch, dict)
            and isinstance(branch.get("actions"), list)
            and bool(branch.get("actions"))
            and all(
                isinstance(action, dict)
                and isinstance(action.get("day_offset"), int)
                and not isinstance(action.get("day_offset"), bool)
                and 0 <= int(action.get("day_offset")) <= 30
                and _non_empty_text(action.get("action"))
                for action in branch.get("actions", [])
            )
            and [int(action.get("day_offset")) for action in branch.get("actions", [])]
            == sorted([int(action.get("day_offset")) for action in branch.get("actions", [])])
            for branch in branches
        )
        for branch in branches:
            for action in branch.get("actions", []):
                if isinstance(action, dict):
                    branch_action_offsets.append(int(action.get("day_offset", 0)))
        if branch_action_offsets:
            max_branch_action_day_offset = max(branch_action_offsets)

    follow_up_actions_pass = False
    max_follow_up_action_day_offset = 0
    if isinstance(follow_up_actions, list) and follow_up_actions:
        action_offsets = [
            int(item.get("day_offset"))
            for item in follow_up_actions
            if isinstance(item, dict)
            and isinstance(item.get("day_offset"), int)
            and not isinstance(item.get("day_offset"), bool)
        ]
        follow_up_actions_pass = (
            len(action_offsets) == len(follow_up_actions)
            and action_offsets == sorted(action_offsets)
            and all(
                isinstance(item, dict)
                and _non_empty_text(item.get("action"))
                and 0 <= int(item.get("day_offset")) <= 30
                for item in follow_up_actions
            )
        )
        if action_offsets:
            max_follow_up_action_day_offset = max(action_offsets)

    expected_max_offset = expectations.get("max_action_day_offset")
    max_day_offset_pass = True
    if isinstance(expected_max_offset, int) and not isinstance(expected_max_offset, bool):
        max_observed = max(max_branch_action_day_offset, max_follow_up_action_day_offset)
        max_day_offset_pass = max_observed <= int(expected_max_offset)

    passed = branch_order_pass and branch_actions_pass and follow_up_actions_pass and max_day_offset_pass
    return (
        passed,
        {
            "branch_order_pass": branch_order_pass,
            "branch_actions_pass": branch_actions_pass,
            "follow_up_actions_pass": follow_up_actions_pass,
            "max_day_offset_pass": max_day_offset_pass,
            "max_branch_action_day_offset": max_branch_action_day_offset,
            "max_follow_up_action_day_offset": max_follow_up_action_day_offset,
        },
    )


def _evidence_link_consistency(
    payload: dict[str, Any],
    expectations: dict[str, Any],
) -> tuple[bool, dict[str, Any]]:
    evidence_links = payload.get("evidence_links")
    concession_ladder = payload.get("concession_ladder")
    objection_playbook = payload.get("objection_playbook")

    if not isinstance(evidence_links, list) or not evidence_links:
        return False, {"evidence_links_present": False}

    fields_pass = all(
        isinstance(link, dict)
        and _non_empty_text(link.get("source_type"))
        and _non_empty_text(link.get("source_id"))
        and _non_empty_text(link.get("detail"))
        for link in evidence_links
    )

    unique_pairs = {
        (str(link.get("source_type", "")), str(link.get("source_id", "")))
        for link in evidence_links
        if isinstance(link, dict)
    }
    unique_pair_pass = len(unique_pairs) == len(evidence_links)

    expected_source_prefix = expectations.get("evidence_source_order_prefix")
    source_prefix_pass = True
    if isinstance(expected_source_prefix, list) and expected_source_prefix:
        actual_sources = [str(link.get("source_type", "")) for link in evidence_links if isinstance(link, dict)]
        expected_sources = [str(value) for value in expected_source_prefix]
        source_prefix_pass = actual_sources[: len(expected_sources)] == expected_sources

    evidence_tokens = [
        f"{str(link.get('source_type', '')).lower()}:{str(link.get('source_id', '')).lower()}"
        for link in evidence_links
        if isinstance(link, dict)
    ]
    evidence_text_parts: list[str] = []
    if isinstance(concession_ladder, list):
        evidence_text_parts.extend(
            [str(item.get("evidence", "")) for item in concession_ladder if isinstance(item, dict)]
        )
    if isinstance(objection_playbook, list):
        evidence_text_parts.extend(
            [str(item.get("evidence", "")) for item in objection_playbook if isinstance(item, dict)]
        )
    evidence_text = " ".join(evidence_text_parts).lower()

    referenced_tokens = [token for token in evidence_tokens if token and token in evidence_text]
    reference_ratio = (len(referenced_tokens) / len(evidence_tokens)) if evidence_tokens else 1.0

    min_ratio = float(expectations.get("min_evidence_reference_ratio", 0.5))
    min_links = int(expectations.get("min_evidence_links", 1))

    min_links_pass = len(evidence_links) >= min_links
    reference_ratio_pass = reference_ratio >= min_ratio

    passed = all([fields_pass, unique_pair_pass, source_prefix_pass, min_links_pass, reference_ratio_pass])
    return (
        passed,
        {
            "fields_pass": fields_pass,
            "unique_pair_pass": unique_pair_pass,
            "source_prefix_pass": source_prefix_pass,
            "min_links_pass": min_links_pass,
            "reference_ratio_pass": reference_ratio_pass,
            "evidence_link_count": len(evidence_links),
            "evidence_reference_ratio": round(reference_ratio, 3),
            "referenced_tokens": referenced_tokens,
        },
    )


def run_benchmark(
    *,
    fixtures_dir: Path = FIXTURE_DIR,
    thresholds: dict[str, float] | None = None,
) -> tuple[dict[str, Any], bool]:
    active_thresholds = dict(DEFAULT_THRESHOLDS)
    if thresholds:
        active_thresholds.update(thresholds)

    app_module = importlib.import_module("api_gateway.app")
    aggregator_module = _load_module("negotiation_quality_aggregator", NEGOTIATION_AGGREGATOR_PATH)
    strategy_module = _load_module("negotiation_quality_strategy", NEGOTIATION_STRATEGY_PATH)
    followup_module = _load_module("negotiation_quality_followup", NEGOTIATION_FOLLOWUP_PATH)
    validator_module = _load_module("core_schema_validator_negotiation_quality", VALIDATOR_PATH)

    negotiation_api = app_module.JobIngestionAPI(
        repository=None,
        extraction_worker=None,
        taxonomy_normalizer=None,
        schema_validator=None,
        candidate_profile_parser=None,
        candidate_storybank_generator=None,
        interview_question_planner=None,
        interview_followup_selector=None,
        progress_aggregator=None,
        trajectory_planner=None,
        negotiation_context_aggregator=aggregator_module.DeterministicNegotiationContextAggregator(),
        negotiation_strategy_generator=strategy_module.DeterministicNegotiationStrategyGenerator(),
        negotiation_followup_planner=followup_module.DeterministicNegotiationFollowupPlanner(),
    )
    validator = validator_module.CoreSchemaValidator.from_file()

    cases = _load_benchmark_cases(fixtures_dir)

    case_reports: list[dict[str, Any]] = []
    strategy_scores: list[float] = []
    cadence_scores: list[float] = []
    boundedness_scores: list[float] = []
    evidence_scores: list[float] = []
    schema_scores: list[float] = []

    for case in cases:
        resolved_request_payload = _resolve_request_payload(case)
        negotiation_plan = negotiation_api._build_negotiation_plan_payload(
            candidate_id=case.candidate_id,
            candidate_profile=case.candidate_profile,
            target_role=case.target_role,
            request_payload=resolved_request_payload,
            interview_history=case.interview_sessions,
            feedback_history=case.feedback_reports,
            latest_trajectory_plan=case.latest_trajectory_plan,
        )
        validation = validator.validate("NegotiationPlan", negotiation_plan)

        strategy_pass, strategy_details = _strategy_structure_quality(negotiation_plan, case.expectations)
        cadence_pass, cadence_details = _follow_up_cadence_quality(negotiation_plan, case.expectations)
        boundedness_pass, boundedness_details = _branch_action_boundedness(negotiation_plan, case.expectations)
        evidence_pass, evidence_details = _evidence_link_consistency(negotiation_plan, case.expectations)
        schema_valid = validation.is_valid

        strategy_scores.append(1.0 if strategy_pass else 0.0)
        cadence_scores.append(1.0 if cadence_pass else 0.0)
        boundedness_scores.append(1.0 if boundedness_pass else 0.0)
        evidence_scores.append(1.0 if evidence_pass else 0.0)
        schema_scores.append(1.0 if schema_valid else 0.0)

        case_quality = _mean(
            [
                1.0 if strategy_pass else 0.0,
                1.0 if cadence_pass else 0.0,
                1.0 if boundedness_pass else 0.0,
                1.0 if evidence_pass else 0.0,
                1.0 if schema_valid else 0.0,
            ]
        )

        case_reports.append(
            {
                "case_id": case.case_id,
                "candidate_id": case.candidate_id,
                "target_role": case.target_role,
                "resolved_request_payload": resolved_request_payload,
                "negotiation_plan": negotiation_plan,
                "strategy_structure_quality_pass": strategy_pass,
                "strategy_structure_details": strategy_details,
                "follow_up_cadence_quality_pass": cadence_pass,
                "follow_up_cadence_details": cadence_details,
                "branch_action_boundedness_pass": boundedness_pass,
                "branch_action_boundedness_details": boundedness_details,
                "evidence_link_consistency_pass": evidence_pass,
                "evidence_link_consistency_details": evidence_details,
                "negotiation_plan_schema_valid": schema_valid,
                "negotiation_plan_schema_issues": [
                    {"path": issue.path, "message": issue.message}
                    for issue in validation.issues
                ],
                "case_quality_score": round(case_quality, 3),
            }
        )

    aggregate = {
        "strategy_structure_quality_rate": round(_mean(strategy_scores), 3),
        "follow_up_cadence_quality_rate": round(_mean(cadence_scores), 3),
        "branch_action_boundedness_rate": round(_mean(boundedness_scores), 3),
        "evidence_link_consistency_rate": round(_mean(evidence_scores), 3),
        "negotiation_plan_schema_valid_rate": round(_mean(schema_scores), 3),
    }
    aggregate["overall_negotiation_quality"] = round(
        _mean(
            [
                aggregate["strategy_structure_quality_rate"],
                aggregate["follow_up_cadence_quality_rate"],
                aggregate["branch_action_boundedness_rate"],
                aggregate["evidence_link_consistency_rate"],
                aggregate["negotiation_plan_schema_valid_rate"],
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
    parser = argparse.ArgumentParser(description="Run deterministic negotiation/follow-up quality benchmark threshold gate.")
    parser.add_argument("--fixtures-dir", default=str(FIXTURE_DIR), help="Directory containing benchmark_*.json fixtures")
    parser.add_argument("--report-path", default=str(DEFAULT_REPORT_PATH), help="Path to write JSON benchmark report")
    parser.add_argument(
        "--min-strategy-structure-quality-rate",
        type=float,
        default=DEFAULT_THRESHOLDS["strategy_structure_quality_rate"],
    )
    parser.add_argument(
        "--min-follow-up-cadence-quality-rate",
        type=float,
        default=DEFAULT_THRESHOLDS["follow_up_cadence_quality_rate"],
    )
    parser.add_argument(
        "--min-branch-action-boundedness-rate",
        type=float,
        default=DEFAULT_THRESHOLDS["branch_action_boundedness_rate"],
    )
    parser.add_argument(
        "--min-evidence-link-consistency-rate",
        type=float,
        default=DEFAULT_THRESHOLDS["evidence_link_consistency_rate"],
    )
    parser.add_argument(
        "--min-negotiation-plan-schema-valid-rate",
        type=float,
        default=DEFAULT_THRESHOLDS["negotiation_plan_schema_valid_rate"],
    )
    parser.add_argument(
        "--min-overall-negotiation-quality",
        type=float,
        default=DEFAULT_THRESHOLDS["overall_negotiation_quality"],
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    report, passed = run_benchmark(
        fixtures_dir=Path(args.fixtures_dir),
        thresholds={
            "strategy_structure_quality_rate": args.min_strategy_structure_quality_rate,
            "follow_up_cadence_quality_rate": args.min_follow_up_cadence_quality_rate,
            "branch_action_boundedness_rate": args.min_branch_action_boundedness_rate,
            "evidence_link_consistency_rate": args.min_evidence_link_consistency_rate,
            "negotiation_plan_schema_valid_rate": args.min_negotiation_plan_schema_valid_rate,
            "overall_negotiation_quality": args.min_overall_negotiation_quality,
        },
    )

    report_path = Path(args.report_path)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
