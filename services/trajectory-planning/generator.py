from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any


DEFAULT_HORIZON_MONTHS = 3
DEFAULT_BASELINE_SCORE = 65.0
MAX_FOCUS_COMPETENCIES = 3

BASE_ROLE_TARGETS: dict[str, float] = {
    "skill.execution": 78.0,
    "skill.communication": 74.0,
    "skill.problem_solving": 77.0,
}

ROLE_TARGET_HINTS: tuple[tuple[tuple[str, ...], dict[str, float]], ...] = (
    (
        ("backend", "api", "platform", "infrastructure", "server"),
        {
            "skill.python": 84.0,
            "skill.sql": 81.0,
            "skill.system_design": 83.0,
            "skill.api_design": 84.0,
        },
    ),
    (
        ("data", "analytics", "machine learning", "ml"),
        {
            "skill.sql": 84.0,
            "skill.data_modeling": 82.0,
            "skill.experimentation": 78.0,
        },
    ),
    (
        ("frontend", "ui", "web", "mobile"),
        {
            "skill.frontend_architecture": 81.0,
            "skill.product_sense": 77.0,
            "skill.communication": 78.0,
        },
    ),
)

LEADERSHIP_ROLE_HINTS = ("manager", "lead", "staff", "principal", "architect")
LEADERSHIP_TARGETS: dict[str, float] = {
    "skill.leadership": 82.0,
    "skill.communication": 80.0,
    "skill.execution": 80.0,
}


@dataclass(frozen=True)
class RankedGap:
    competency: str
    current_score: float
    target_score: float
    delta_score: float
    gap_score: float
    observation_count: int
    priority: float


class DeterministicTrajectoryPlanner:
    """Deterministic trajectory milestone + weekly-plan generator."""

    def __init__(self, *, horizon_months: int = DEFAULT_HORIZON_MONTHS) -> None:
        self._horizon_months = max(1, min(24, int(horizon_months)))

    def generate(
        self,
        *,
        candidate_profile: dict[str, Any],
        target_role: str,
        progress_summary: dict[str, Any],
        reference_date: date | None = None,
    ) -> dict[str, Any]:
        current_date = reference_date or datetime.now(timezone.utc).date()

        role_targets = _infer_role_targets(target_role)
        candidate_scores = _normalize_candidate_scores(candidate_profile.get("skills"))
        trend_map = _normalize_trend_map(progress_summary.get("competency_trends"))
        top_risk = _normalize_competency_list(progress_summary.get("top_risk_competencies"))

        current_overall = _extract_progress_score(progress_summary, section="current")
        fallback_current = current_overall if current_overall is not None else _average_score(candidate_scores, fallback=DEFAULT_BASELINE_SCORE)
        ranked_gaps = _rank_gaps(
            role_targets=role_targets,
            candidate_scores=candidate_scores,
            trend_map=trend_map,
            top_risk=top_risk,
            fallback_current=fallback_current,
        )
        focus = ranked_gaps[:MAX_FOCUS_COMPETENCIES]
        if not focus:
            focus = _fallback_focus(role_targets=role_targets, fallback_current=fallback_current)

        role_readiness = round(
            current_overall if current_overall is not None else _average_score({item.competency: item.current_score for item in focus}, fallback=DEFAULT_BASELINE_SCORE),
            2,
        )
        role_readiness = max(0.0, min(100.0, role_readiness))

        baseline_overall = _extract_progress_score(progress_summary, section="baseline")
        history_counts = progress_summary.get("history_counts")
        snapshots = 0
        if isinstance(history_counts, dict):
            try:
                snapshots = max(0, int(history_counts.get("snapshots", 0)))
            except (TypeError, ValueError):
                snapshots = 0

        milestones = _build_milestones(
            current_date=current_date,
            target_role=target_role,
            focus=focus,
            baseline_overall=baseline_overall,
            current_overall=role_readiness,
        )
        weekly_plan = _build_weekly_plan(
            focus=focus,
            snapshots=snapshots,
        )

        return {
            "horizon_months": self._horizon_months,
            "role_readiness_score": role_readiness,
            "milestones": milestones,
            "weekly_plan": weekly_plan,
        }


def _infer_role_targets(target_role: str) -> dict[str, float]:
    role_text = str(target_role).strip().lower()
    targets = dict(BASE_ROLE_TARGETS)

    for hints, hinted_targets in ROLE_TARGET_HINTS:
        if any(token in role_text for token in hints):
            targets.update(hinted_targets)

    if any(token in role_text for token in LEADERSHIP_ROLE_HINTS):
        targets.update(LEADERSHIP_TARGETS)

    adjustment = 0.0
    if "principal" in role_text:
        adjustment = 6.0
    elif "staff" in role_text:
        adjustment = 4.0
    elif "senior" in role_text or "lead" in role_text:
        adjustment = 3.0
    elif "junior" in role_text or "associate" in role_text:
        adjustment = -3.0

    normalized: dict[str, float] = {}
    for competency, score in targets.items():
        adjusted = _round_score(max(55.0, min(95.0, score + adjustment)))
        normalized[_normalize_competency(competency)] = adjusted
    return normalized


def _normalize_candidate_scores(raw_skills: Any) -> dict[str, float]:
    if not isinstance(raw_skills, dict):
        return {}

    normalized: dict[str, float] = {}
    for raw_competency, raw_score in raw_skills.items():
        competency = _normalize_competency(raw_competency)
        if not competency:
            continue
        try:
            value = float(raw_score)
        except (TypeError, ValueError):
            continue
        if 0.0 <= value <= 1.0:
            value *= 100.0
        normalized[competency] = _round_score(max(0.0, min(100.0, value)))
    return normalized


def _normalize_trend_map(raw_trends: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(raw_trends, list):
        return {}

    trend_map: dict[str, dict[str, Any]] = {}
    for raw in raw_trends:
        if not isinstance(raw, dict):
            continue
        competency = _normalize_competency(raw.get("competency"))
        if not competency:
            continue
        current_score = _coerce_score(raw.get("current_score"))
        delta_score = _coerce_delta(raw.get("delta_score"))
        if current_score is None:
            continue
        baseline_score = _coerce_score(raw.get("baseline_score"))
        observation_count = _coerce_nonnegative_int(raw.get("observation_count"))
        trend_map[competency] = {
            "competency": competency,
            "baseline_score": baseline_score if baseline_score is not None else current_score,
            "current_score": current_score,
            "delta_score": delta_score,
            "observation_count": observation_count,
        }
    return trend_map


def _normalize_competency_list(raw_items: Any) -> list[str]:
    if not isinstance(raw_items, list):
        return []
    seen: set[str] = set()
    ordered: list[str] = []
    for raw in raw_items:
        competency = _normalize_competency(raw)
        if not competency or competency in seen:
            continue
        seen.add(competency)
        ordered.append(competency)
    return ordered


def _extract_progress_score(progress_summary: dict[str, Any], *, section: str) -> float | None:
    raw_section = progress_summary.get(section)
    if not isinstance(raw_section, dict):
        return None
    return _coerce_score(raw_section.get("overall_score"))


def _rank_gaps(
    *,
    role_targets: dict[str, float],
    candidate_scores: dict[str, float],
    trend_map: dict[str, dict[str, Any]],
    top_risk: list[str],
    fallback_current: float,
) -> list[RankedGap]:
    competencies = sorted(set(role_targets.keys()) | set(candidate_scores.keys()) | set(trend_map.keys()) | set(top_risk))
    ranked: list[RankedGap] = []

    for competency in competencies:
        trend = trend_map.get(competency)
        current_score = (
            float(trend["current_score"])
            if trend is not None
            else float(candidate_scores.get(competency, fallback_current))
        )
        delta_score = float(trend["delta_score"]) if trend is not None else 0.0
        observation_count = int(trend["observation_count"]) if trend is not None else 0
        target_score = float(role_targets.get(competency, _fallback_target_score(competency, role_targets)))
        gap_score = _round_score(max(0.0, target_score - current_score))

        downward_trend = max(0.0, -delta_score)
        risk_bonus = 0.0
        if competency in top_risk:
            rank = top_risk.index(competency)
            risk_bonus = float(max(2, 6 - (rank * 2)))
        if observation_count <= 1:
            risk_bonus += 2.0

        priority = _round_score((gap_score * 0.62) + (downward_trend * 0.28) + risk_bonus)
        ranked.append(
            RankedGap(
                competency=competency,
                current_score=_round_score(current_score),
                target_score=_round_score(target_score),
                delta_score=_round_score(delta_score),
                gap_score=gap_score,
                observation_count=max(0, observation_count),
                priority=priority,
            )
        )

    ranked.sort(
        key=lambda item: (
            -item.priority,
            -item.gap_score,
            item.current_score,
            item.competency,
        )
    )
    return ranked


def _fallback_focus(*, role_targets: dict[str, float], fallback_current: float) -> list[RankedGap]:
    prioritized = sorted(role_targets.items(), key=lambda item: (-item[1], item[0]))[:MAX_FOCUS_COMPETENCIES]
    if not prioritized:
        prioritized = [("skill.execution", 78.0), ("skill.communication", 74.0), ("skill.problem_solving", 77.0)]

    focus: list[RankedGap] = []
    for competency, target_score in prioritized:
        gap_score = _round_score(max(0.0, float(target_score) - fallback_current))
        focus.append(
            RankedGap(
                competency=competency,
                current_score=_round_score(fallback_current),
                target_score=_round_score(float(target_score)),
                delta_score=0.0,
                gap_score=gap_score,
                observation_count=0,
                priority=gap_score,
            )
        )
    return focus


def _build_milestones(
    *,
    current_date: date,
    target_role: str,
    focus: list[RankedGap],
    baseline_overall: float | None,
    current_overall: float,
) -> list[dict[str, str]]:
    first = focus[0]
    second = focus[1] if len(focus) > 1 else first
    third = focus[2] if len(focus) > 2 else second

    first_goal = _goal_score(first)
    second_goal = _goal_score(second)
    third_goal = _goal_score(third)
    combined_gap = _round_score(first.gap_score + second.gap_score)

    readiness_target = _round_score(
        min(
            90.0,
            max(
                current_overall + 8.0,
                (first_goal + second_goal + third_goal) / 3.0,
            ),
        )
    )
    baseline_text = "n/a" if baseline_overall is None else f"{baseline_overall:.1f}"

    return [
        {
            "name": f"Stabilize {_competency_label(first.competency)} signal for {target_role}",
            "target_date": (current_date + timedelta(days=14)).isoformat(),
            "metric": (
                f"Move {_competency_label(first.competency)} from current={first.current_score:.1f} "
                f"to >= {first_goal:.1f} (target={first.target_score:.1f}, delta={first.delta_score:+.1f})."
            ),
        },
        {
            "name": f"Close highest role gaps for {target_role}",
            "target_date": (current_date + timedelta(days=42)).isoformat(),
            "metric": (
                f"Reduce combined gap for {_competency_label(first.competency)} and {_competency_label(second.competency)} "
                f"from {combined_gap:.1f} points while reaching >={first_goal:.1f}/{second_goal:.1f}."
            ),
        },
        {
            "name": f"Demonstrate consistent readiness trend for {target_role}",
            "target_date": (current_date + timedelta(days=84)).isoformat(),
            "metric": (
                f"Lift overall score from baseline={baseline_text} and current={current_overall:.1f} "
                f"to >= {readiness_target:.1f} while keeping top-focus deltas non-negative."
            ),
        },
    ]


def _build_weekly_plan(*, focus: list[RankedGap], snapshots: int) -> list[dict[str, Any]]:
    max_gap = max((item.gap_score for item in focus), default=0.0)
    negative_delta_count = sum(1 for item in focus if item.delta_score < 0.0)
    weeks = 4
    if len(focus) >= 2:
        weeks += 1
    if max_gap >= 18.0:
        weeks += 1
    if negative_delta_count >= 2:
        weeks += 1
    weeks = max(4, min(8, weeks))

    plan: list[dict[str, Any]] = []
    for week in range(1, weeks + 1):
        primary = focus[(week - 1) % len(focus)]
        secondary = focus[week % len(focus)]
        actions = _weekly_actions(week=week, total_weeks=weeks, primary=primary, secondary=secondary, snapshots=snapshots)
        plan.append({"week": week, "actions": actions})
    return plan


def _weekly_actions(
    *,
    week: int,
    total_weeks: int,
    primary: RankedGap,
    secondary: RankedGap,
    snapshots: int,
) -> list[str]:
    if week <= max(1, total_weeks // 4):
        return [
            (
                f"Baseline {_competency_label(primary.competency)} with current={primary.current_score:.1f}, "
                f"target={primary.target_score:.1f}, delta={primary.delta_score:+.1f}; capture one STAR rewrite with metrics."
            ),
            (
                f"Use snapshots={snapshots} to compare {_competency_label(primary.competency)} and "
                f"{_competency_label(secondary.competency)}; log one root-cause hypothesis for the larger gap."
            ),
        ]
    if week <= max(2, total_weeks // 2):
        return [
            (
                f"Run two timed drills on {_competency_label(primary.competency)} and move toward "
                f"goal={_goal_score(primary):.1f} from current={primary.current_score:.1f}."
            ),
            (
                f"Add one evidence-backed story for {_competency_label(secondary.competency)} and keep "
                f"delta above {secondary.delta_score:+.1f} on the next mock."
            ),
        ]
    if week < total_weeks:
        return [
            (
                f"Simulate mixed interview rounds prioritizing {_competency_label(primary.competency)} then "
                f"{_competency_label(secondary.competency)} against target={primary.target_score:.1f}."
            ),
            (
                f"After simulation, update evidence and shrink {_competency_label(primary.competency)} "
                f"gap from baseline={primary.gap_score:.1f} points."
            ),
        ]
    return [
        (
            f"Run a full rehearsal and maintain {_competency_label(primary.competency)} at >= {_goal_score(primary):.1f} "
            f"while monitoring delta={primary.delta_score:+.1f}."
        ),
        (
            f"Re-rank next-cycle priorities using snapshots={snapshots} and remaining gaps for "
            f"{_competency_label(primary.competency)} and {_competency_label(secondary.competency)}."
        ),
    ]


def _goal_score(item: RankedGap) -> float:
    if item.gap_score <= 0.0:
        return _round_score(min(100.0, item.current_score + 4.0))
    improvement = min(14.0, max(6.0, item.gap_score))
    return _round_score(min(item.target_score, item.current_score + improvement))


def _fallback_target_score(competency: str, role_targets: dict[str, float]) -> float:
    if competency in role_targets:
        return role_targets[competency]
    if competency.startswith("skill.communication"):
        return 78.0
    if competency.startswith("skill.execution"):
        return 80.0
    return 76.0


def _average_score(scores: dict[str, float], *, fallback: float) -> float:
    if not scores:
        return _round_score(fallback)
    return _round_score(sum(scores.values()) / float(len(scores)))


def _normalize_competency(raw_value: Any) -> str:
    if not isinstance(raw_value, str):
        return ""
    value = raw_value.strip().lower()
    if not value:
        return ""
    if value.startswith("skill."):
        return value
    return f"skill.{value}"


def _competency_label(competency: str) -> str:
    label = competency.replace("skill.", "").replace("_", " ").strip()
    if not label:
        return "execution"
    return label


def _coerce_score(raw_value: Any) -> float | None:
    try:
        value = float(raw_value)
    except (TypeError, ValueError):
        return None
    return _round_score(max(0.0, min(100.0, value)))


def _coerce_delta(raw_value: Any) -> float:
    try:
        value = float(raw_value)
    except (TypeError, ValueError):
        return 0.0
    return _round_score(max(-100.0, min(100.0, value)))


def _coerce_nonnegative_int(raw_value: Any) -> int:
    try:
        value = int(raw_value)
    except (TypeError, ValueError):
        return 0
    return max(0, value)


def _round_score(value: float) -> float:
    return round(float(value), 2)

