from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


SIGNAL_STRENGTH_HIGH = 75.0
SIGNAL_STRENGTH_MEDIUM = 60.0

SIGNAL_SEVERITY_CRITICAL = 80.0
SIGNAL_SEVERITY_HIGH = 62.0
SIGNAL_SEVERITY_MEDIUM = 38.0

ROLE_MARKET_HINTS: tuple[tuple[tuple[str, ...], float], ...] = (
    (("principal",), 0.10),
    (("staff",), 0.08),
    (("senior", "lead"), 0.06),
    (("junior", "associate"), 0.02),
)


@dataclass(frozen=True)
class _ScoreSnapshot:
    source_type: str
    source_id: str
    timestamp: str
    overall_score: float


class DeterministicNegotiationContextAggregator:
    """Deterministic negotiation-context aggregation from offer + performance history."""

    def aggregate(
        self,
        *,
        candidate_id: str,
        target_role: str,
        request_payload: dict[str, Any],
        candidate_profile: dict[str, Any],
        interview_sessions: list[dict[str, Any]],
        feedback_reports: list[dict[str, Any]],
        latest_trajectory_plan: dict[str, Any] | None,
    ) -> dict[str, Any]:
        snapshots = _collect_score_snapshots(interview_sessions=interview_sessions, feedback_reports=feedback_reports)
        baseline_score, current_score, momentum_score = _score_trend_summary(snapshots=snapshots)
        top_skills = _top_candidate_skills(candidate_profile.get("skills"))
        skill_depth_score = _skill_depth_score(top_skills)

        trajectory_readiness = _coerce_score(
            latest_trajectory_plan.get("role_readiness_score") if isinstance(latest_trajectory_plan, dict) else None
        )
        readiness_score = trajectory_readiness if trajectory_readiness is not None else current_score

        leverage_signals = _build_leverage_signals(
            skill_depth_score=skill_depth_score,
            readiness_score=readiness_score,
            momentum_score=momentum_score,
            top_skills=top_skills,
            baseline_score=baseline_score,
            current_score=current_score,
            latest_trajectory_plan=latest_trajectory_plan,
        )
        risk_signals = _build_risk_signals(
            target_role=target_role,
            request_payload=request_payload,
            readiness_score=readiness_score,
            momentum_score=momentum_score,
        )

        leverage_average = _round_score(_mean([float(item["score"]) for item in leverage_signals]))
        risk_average = _round_score(_mean([float(item["score"]) for item in risk_signals]))
        adjustments = _compensation_adjustments(
            target_role=target_role,
            readiness_score=readiness_score,
            momentum_score=momentum_score,
            leverage_average=leverage_average,
            risk_average=risk_average,
            interview_count=len(interview_sessions),
            feedback_count=len(feedback_reports),
            has_trajectory=isinstance(latest_trajectory_plan, dict),
        )

        evidence_links = _build_evidence_links(
            candidate_id=candidate_id,
            request_payload=request_payload,
            top_skills=top_skills,
            snapshots=snapshots,
            latest_trajectory_plan=latest_trajectory_plan,
        )

        return {
            "history_counts": {
                "interview_sessions": len(interview_sessions),
                "feedback_reports": len(feedback_reports),
                "snapshots": len(snapshots),
                "trajectory_plans": 1 if isinstance(latest_trajectory_plan, dict) else 0,
            },
            "leverage_signals": leverage_signals,
            "risk_signals": risk_signals,
            "evidence_links": evidence_links,
            "compensation_adjustments": adjustments,
        }


def _collect_score_snapshots(
    *,
    interview_sessions: list[dict[str, Any]],
    feedback_reports: list[dict[str, Any]],
) -> list[_ScoreSnapshot]:
    snapshots: list[_ScoreSnapshot] = []

    for session in interview_sessions:
        if not isinstance(session, dict):
            continue
        session_id = str(session.get("session_id", "")).strip()
        if not session_id:
            continue

        overall_score = _coerce_score(session.get("overall_score"))
        if overall_score is None:
            overall_score = _average_scores(session.get("scores"))
        if overall_score is None:
            continue

        snapshots.append(
            _ScoreSnapshot(
                source_type="interview_session",
                source_id=session_id,
                timestamp=_normalize_timestamp(session.get("created_at")),
                overall_score=overall_score,
            )
        )

    for report in feedback_reports:
        if not isinstance(report, dict):
            continue
        report_id = str(report.get("feedback_report_id", "")).strip()
        if not report_id:
            continue

        overall_score = _coerce_score(report.get("overall_score"))
        if overall_score is None:
            overall_score = _average_scores(report.get("competency_scores"))
        if overall_score is None:
            continue

        snapshots.append(
            _ScoreSnapshot(
                source_type="feedback_report",
                source_id=report_id,
                timestamp=_normalize_timestamp(report.get("generated_at")),
                overall_score=overall_score,
            )
        )

    snapshots.sort(
        key=lambda item: (
            item.timestamp,
            0 if item.source_type == "interview_session" else 1,
            item.source_id,
        )
    )
    return snapshots


def _score_trend_summary(*, snapshots: list[_ScoreSnapshot]) -> tuple[float, float, float]:
    if not snapshots:
        return 65.0, 65.0, 50.0

    baseline = snapshots[0].overall_score
    current = snapshots[-1].overall_score
    delta = current - baseline
    momentum = _clamp(50.0 + (delta * 2.0), 0.0, 100.0)
    return _round_score(baseline), _round_score(current), _round_score(momentum)


def _top_candidate_skills(raw_skills: Any, *, limit: int = 3) -> list[tuple[str, float]]:
    if not isinstance(raw_skills, dict):
        return []

    ranked: list[tuple[str, float]] = []
    for raw_skill, raw_score in raw_skills.items():
        if not isinstance(raw_skill, str):
            continue
        score = _coerce_score(raw_score)
        if score is None:
            continue
        skill = _normalize_competency(raw_skill)
        if not skill:
            continue
        ranked.append((skill, score))

    ranked.sort(key=lambda item: (-item[1], item[0]))
    return ranked[: max(0, int(limit))]


def _skill_depth_score(top_skills: list[tuple[str, float]]) -> float:
    if not top_skills:
        return 62.0
    return _round_score(_mean([score for _, score in top_skills]))


def _build_leverage_signals(
    *,
    skill_depth_score: float,
    readiness_score: float,
    momentum_score: float,
    top_skills: list[tuple[str, float]],
    baseline_score: float,
    current_score: float,
    latest_trajectory_plan: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    skill_labels = ", ".join(_competency_label(skill) for skill, _ in top_skills) or "candidate skill profile"
    trajectory_plan_id = ""
    if isinstance(latest_trajectory_plan, dict):
        trajectory_plan_id = str(latest_trajectory_plan.get("trajectory_plan_id", "")).strip()
    trajectory_evidence = (
        f"Latest trajectory readiness signal from {trajectory_plan_id or 'trajectory context'} "
        f"is {readiness_score:.2f}."
    )

    signals = [
        {
            "signal": "trajectory_readiness",
            "strength": _strength_bucket(readiness_score),
            "score": _round_score(readiness_score),
            "evidence": trajectory_evidence,
        },
        {
            "signal": "skill_depth",
            "strength": _strength_bucket(skill_depth_score),
            "score": _round_score(skill_depth_score),
            "evidence": f"Top transferable skills: {skill_labels}.",
        },
        {
            "signal": "recent_momentum",
            "strength": _strength_bucket(momentum_score),
            "score": _round_score(momentum_score),
            "evidence": f"Interview/feedback trend moved from {baseline_score:.2f} to {current_score:.2f}.",
        },
    ]
    signals.sort(key=lambda item: (-float(item["score"]), str(item["signal"])))
    return signals


def _build_risk_signals(
    *,
    target_role: str,
    request_payload: dict[str, Any],
    readiness_score: float,
    momentum_score: float,
) -> list[dict[str, Any]]:
    deadline_score, deadline_evidence = _deadline_pressure_risk(request_payload.get("offer_deadline_date"))
    compression_score, compression_evidence = _compensation_compression_risk(request_payload=request_payload)
    role_gap_score = _round_score(
        _clamp((_role_target_score(target_role) - readiness_score) * 1.9, 0.0, 100.0)
    )

    signals = [
        {
            "signal": "deadline_pressure",
            "severity": _severity_bucket(deadline_score),
            "score": deadline_score,
            "evidence": deadline_evidence,
        },
        {
            "signal": "trajectory_gap",
            "severity": _severity_bucket(role_gap_score),
            "score": role_gap_score,
            "evidence": (
                f"Target role benchmark {_role_target_score(target_role):.2f} vs readiness "
                f"{readiness_score:.2f} indicates execution gap."
            ),
        },
        {
            "signal": "momentum_volatility",
            "severity": _severity_bucket(_round_score(100.0 - momentum_score)),
            "score": _round_score(100.0 - momentum_score),
            "evidence": f"Momentum signal {momentum_score:.2f} leaves volatility exposure for negotiation timing.",
        },
        {
            "signal": "compensation_compression",
            "severity": _severity_bucket(compression_score),
            "score": compression_score,
            "evidence": compression_evidence,
        },
    ]
    signals.sort(
        key=lambda item: (
            -_severity_rank(str(item["severity"])),
            -float(item["score"]),
            str(item["signal"]),
        )
    )
    return signals


def _deadline_pressure_risk(raw_offer_deadline_date: Any) -> tuple[float, str]:
    if not isinstance(raw_offer_deadline_date, str) or not raw_offer_deadline_date.strip():
        return 28.0, "No explicit offer deadline provided; moderate scheduling uncertainty remains."

    deadline_text = raw_offer_deadline_date.strip()
    try:
        deadline = datetime.fromisoformat(deadline_text).date()
    except ValueError:
        try:
            deadline = datetime.strptime(deadline_text, "%Y-%m-%d").date()
        except ValueError:
            return 42.0, "Offer deadline format is ambiguous; timeline pressure cannot be calibrated precisely."

    today = datetime.now(timezone.utc).date()
    days_until_deadline = (deadline - today).days
    if days_until_deadline <= 3:
        return 86.0, f"Offer deadline is {days_until_deadline} day(s) away, increasing negotiation pressure."
    if days_until_deadline <= 7:
        return 70.0, f"Offer deadline is {days_until_deadline} day(s) away, limiting negotiation runway."
    if days_until_deadline <= 14:
        return 46.0, f"Offer deadline is {days_until_deadline} day(s) away; timeline risk is manageable."
    return 24.0, f"Offer deadline is {days_until_deadline} day(s) away, leaving room for negotiation cadence."


def _compensation_compression_risk(*, request_payload: dict[str, Any]) -> tuple[float, str]:
    current_salary = _coerce_nonnegative_int(request_payload.get("current_base_salary"))
    target_salary = _coerce_nonnegative_int(request_payload.get("target_base_salary"))
    if current_salary is None or target_salary is None:
        return 34.0, "Current/target salary pair is partial; compensation spread risk is estimated conservatively."

    delta = target_salary - current_salary
    if delta < 12000:
        return 64.0, f"Target delta of {delta} may understate upside and weaken anchor credibility."
    if delta > 50000:
        return 74.0, f"Target delta of {delta} may trigger budget-pushback risk."
    return 30.0, f"Target delta of {delta} is within a typical negotiation spread."


def _compensation_adjustments(
    *,
    target_role: str,
    readiness_score: float,
    momentum_score: float,
    leverage_average: float,
    risk_average: float,
    interview_count: int,
    feedback_count: int,
    has_trajectory: bool,
) -> dict[str, float]:
    market_uplift_pct = _role_market_uplift(target_role)
    readiness_uplift_pct = _clamp((readiness_score - 60.0) / 100.0 * 0.08, -0.02, 0.08)
    momentum_uplift_pct = _clamp((momentum_score - 50.0) / 100.0 * 0.05, -0.03, 0.03)
    risk_discount_pct = _clamp((risk_average / 100.0) * 0.07, 0.01, 0.08)
    total_uplift_pct = _clamp(
        market_uplift_pct + readiness_uplift_pct + momentum_uplift_pct - risk_discount_pct,
        -0.04,
        0.16,
    )
    walk_away_floor_pct = _clamp(0.90 + ((leverage_average - risk_average) / 100.0 * 0.06), 0.86, 0.96)

    confidence = _clamp(
        0.58
        + (min(interview_count, 4) * 0.04)
        + (min(feedback_count, 4) * 0.03)
        + (0.08 if has_trajectory else 0.0),
        0.50,
        0.95,
    )
    return {
        "market_uplift_pct": _round_score(market_uplift_pct),
        "readiness_uplift_pct": _round_score(readiness_uplift_pct),
        "momentum_uplift_pct": _round_score(momentum_uplift_pct),
        "risk_discount_pct": _round_score(risk_discount_pct),
        "total_uplift_pct": _round_score(total_uplift_pct),
        "walk_away_floor_pct": _round_score(walk_away_floor_pct),
        "confidence": _round_score(confidence),
    }


def _build_evidence_links(
    *,
    candidate_id: str,
    request_payload: dict[str, Any],
    top_skills: list[tuple[str, float]],
    snapshots: list[_ScoreSnapshot],
    latest_trajectory_plan: dict[str, Any] | None,
) -> list[dict[str, str]]:
    links: list[dict[str, str]] = []

    current_base_salary = _coerce_nonnegative_int(request_payload.get("current_base_salary"))
    target_base_salary = _coerce_nonnegative_int(request_payload.get("target_base_salary"))
    links.append(
        {
            "source_type": "offer_input",
            "source_id": candidate_id,
            "detail": (
                f"Offer context: current_base_salary={current_base_salary}, "
                f"target_base_salary={target_base_salary}."
            ),
        }
    )

    if top_skills:
        labels = ", ".join(_competency_label(skill) for skill, _ in top_skills)
        links.append(
            {
                "source_type": "candidate_profile",
                "source_id": candidate_id,
                "detail": f"Top skills used in leverage scoring: {labels}.",
            }
        )

    if snapshots:
        baseline = snapshots[0]
        current = snapshots[-1]
        links.append(
            {
                "source_type": baseline.source_type,
                "source_id": baseline.source_id,
                "detail": f"Baseline performance snapshot score={baseline.overall_score:.2f}.",
            }
        )
        links.append(
            {
                "source_type": current.source_type,
                "source_id": current.source_id,
                "detail": f"Latest performance snapshot score={current.overall_score:.2f}.",
            }
        )

    if isinstance(latest_trajectory_plan, dict):
        trajectory_plan_id = str(latest_trajectory_plan.get("trajectory_plan_id", "")).strip()
        if trajectory_plan_id:
            readiness = _coerce_score(latest_trajectory_plan.get("role_readiness_score"))
            links.append(
                {
                    "source_type": "trajectory_plan",
                    "source_id": trajectory_plan_id,
                    "detail": f"Latest role readiness signal={readiness if readiness is not None else 'n/a'}.",
                }
            )

    order = {
        "offer_input": 0,
        "candidate_profile": 1,
        "interview_session": 2,
        "feedback_report": 3,
        "trajectory_plan": 4,
    }
    deduped: dict[tuple[str, str, str], dict[str, str]] = {}
    for link in links:
        key = (str(link["source_type"]), str(link["source_id"]), str(link["detail"]))
        deduped[key] = link

    ordered = sorted(
        deduped.values(),
        key=lambda item: (
            order.get(str(item["source_type"]), 99),
            str(item["source_id"]),
            str(item["detail"]),
        ),
    )
    return ordered[:5]


def _average_scores(raw_scores: Any) -> float | None:
    if not isinstance(raw_scores, dict):
        return None
    values: list[float] = []
    for raw in raw_scores.values():
        score = _coerce_score(raw)
        if score is None:
            continue
        values.append(score)
    if not values:
        return None
    return _round_score(_mean(values))


def _role_market_uplift(target_role: str) -> float:
    role_text = str(target_role).strip().lower()
    for hints, uplift in ROLE_MARKET_HINTS:
        if any(token in role_text for token in hints):
            return uplift
    return 0.04


def _role_target_score(target_role: str) -> float:
    role_text = str(target_role).strip().lower()
    base = 74.0
    if "principal" in role_text:
        return 86.0
    if "staff" in role_text:
        return 82.0
    if "senior" in role_text or "lead" in role_text:
        return 79.0
    if "junior" in role_text or "associate" in role_text:
        return 70.0
    return base


def _strength_bucket(score: float) -> str:
    if score >= SIGNAL_STRENGTH_HIGH:
        return "high"
    if score >= SIGNAL_STRENGTH_MEDIUM:
        return "medium"
    return "low"


def _severity_bucket(score: float) -> str:
    if score >= SIGNAL_SEVERITY_CRITICAL:
        return "critical"
    if score >= SIGNAL_SEVERITY_HIGH:
        return "high"
    if score >= SIGNAL_SEVERITY_MEDIUM:
        return "medium"
    return "low"


def _severity_rank(label: str) -> int:
    if label == "critical":
        return 3
    if label == "high":
        return 2
    if label == "medium":
        return 1
    return 0


def _normalize_competency(raw_value: Any) -> str:
    if not isinstance(raw_value, str):
        return ""
    normalized = raw_value.strip().lower()
    if not normalized:
        return ""
    if normalized.startswith("skill."):
        return normalized
    return f"skill.{normalized.replace(' ', '_')}"


def _competency_label(competency: str) -> str:
    normalized = str(competency).strip().lower()
    if normalized.startswith("skill."):
        normalized = normalized[len("skill.") :]
    return normalized.replace("_", " ")


def _normalize_timestamp(raw_value: Any) -> str:
    if isinstance(raw_value, str) and raw_value.strip():
        return raw_value.strip()
    return "1970-01-01T00:00:00+00:00"


def _coerce_score(raw_value: Any) -> float | None:
    if not isinstance(raw_value, (int, float)) or isinstance(raw_value, bool):
        return None
    score = float(raw_value)
    if 0.0 <= score <= 1.0:
        score *= 100.0
    return _round_score(_clamp(score, 0.0, 100.0))


def _coerce_nonnegative_int(raw_value: Any) -> int | None:
    if not isinstance(raw_value, int) or isinstance(raw_value, bool):
        return None
    if raw_value < 0:
        return None
    return int(raw_value)


def _mean(values: list[float]) -> float:
    if not values:
        return 0.0
    return sum(values) / len(values)


def _round_score(value: float) -> float:
    return round(float(value), 2)


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, float(value)))
