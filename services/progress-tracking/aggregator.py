from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class ProgressSnapshot:
    source_type: str
    source_id: str
    timestamp: str
    overall_score: float | None
    competency_scores: dict[str, float]


class LongitudinalProgressAggregator:
    """Deterministic longitudinal progress aggregator across interview and feedback history."""

    def aggregate(
        self,
        *,
        interview_sessions: list[dict[str, Any]],
        feedback_reports: list[dict[str, Any]],
    ) -> dict[str, Any]:
        snapshots = _collect_snapshots(interview_sessions=interview_sessions, feedback_reports=feedback_reports)
        if not snapshots:
            return {
                "history_counts": {
                    "interview_sessions": len(interview_sessions),
                    "feedback_reports": len(feedback_reports),
                    "snapshots": 0,
                },
                "baseline": {},
                "current": {},
                "delta": {},
                "competency_trends": [],
                "top_improving_competencies": [],
                "top_risk_competencies": [],
            }

        baseline_snapshot = snapshots[0]
        current_snapshot = snapshots[-1]

        baseline_overall = baseline_snapshot.overall_score
        current_overall = current_snapshot.overall_score
        delta_overall = _round_score(current_overall - baseline_overall) if baseline_overall is not None and current_overall is not None else None

        competency_trends = _build_competency_trends(snapshots=snapshots)
        top_improving = [entry["competency"] for entry in competency_trends if float(entry["delta_score"]) > 0][:3]
        top_risk = [entry["competency"] for entry in sorted(competency_trends, key=lambda item: (float(item["current_score"]), str(item["competency"])))][:3]

        return {
            "history_counts": {
                "interview_sessions": len(interview_sessions),
                "feedback_reports": len(feedback_reports),
                "snapshots": len(snapshots),
            },
            "baseline": {
                "timestamp": baseline_snapshot.timestamp,
                "source_type": baseline_snapshot.source_type,
                "source_id": baseline_snapshot.source_id,
                "overall_score": baseline_overall,
            },
            "current": {
                "timestamp": current_snapshot.timestamp,
                "source_type": current_snapshot.source_type,
                "source_id": current_snapshot.source_id,
                "overall_score": current_overall,
            },
            "delta": {
                "overall_score": delta_overall,
            },
            "competency_trends": competency_trends,
            "top_improving_competencies": top_improving,
            "top_risk_competencies": top_risk,
        }


def _collect_snapshots(
    *,
    interview_sessions: list[dict[str, Any]],
    feedback_reports: list[dict[str, Any]],
) -> list[ProgressSnapshot]:
    snapshots: list[ProgressSnapshot] = []

    for session in interview_sessions:
        session_id = str(session.get("session_id", "")).strip()
        if not session_id:
            continue
        timestamp = _normalize_timestamp(session.get("created_at"))
        competency_scores = _normalize_score_map(session.get("scores"))
        if not competency_scores:
            competency_scores = _derive_session_scores_from_questions(session.get("questions"))

        overall_score = _coerce_score(session.get("overall_score"))
        if overall_score is None and competency_scores:
            overall_score = _round_score(sum(competency_scores.values()) / float(len(competency_scores)))

        if overall_score is None and not competency_scores:
            continue
        snapshots.append(
            ProgressSnapshot(
                source_type="interview_session",
                source_id=session_id,
                timestamp=timestamp,
                overall_score=overall_score,
                competency_scores=competency_scores,
            )
        )

    for report in feedback_reports:
        report_id = str(report.get("feedback_report_id", "")).strip()
        if not report_id:
            continue
        timestamp = _normalize_timestamp(report.get("generated_at"))
        competency_scores = _normalize_score_map(report.get("competency_scores"))
        overall_score = _coerce_score(report.get("overall_score"))
        if overall_score is None and competency_scores:
            overall_score = _round_score(sum(competency_scores.values()) / float(len(competency_scores)))
        if overall_score is None and not competency_scores:
            continue
        snapshots.append(
            ProgressSnapshot(
                source_type="feedback_report",
                source_id=report_id,
                timestamp=timestamp,
                overall_score=overall_score,
                competency_scores=competency_scores,
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


def _build_competency_trends(*, snapshots: list[ProgressSnapshot]) -> list[dict[str, Any]]:
    first_scores: dict[str, float] = {}
    last_scores: dict[str, float] = {}
    observation_counts: dict[str, int] = {}

    for snapshot in snapshots:
        for competency, score in snapshot.competency_scores.items():
            if competency not in first_scores:
                first_scores[competency] = score
            last_scores[competency] = score
            observation_counts[competency] = observation_counts.get(competency, 0) + 1

    trends: list[dict[str, Any]] = []
    for competency in sorted(first_scores):
        baseline_score = _round_score(first_scores[competency])
        current_score = _round_score(last_scores[competency])
        delta_score = _round_score(current_score - baseline_score)
        trends.append(
            {
                "competency": competency,
                "baseline_score": baseline_score,
                "current_score": current_score,
                "delta_score": delta_score,
                "observation_count": int(observation_counts.get(competency, 0)),
            }
        )

    trends.sort(key=lambda item: (-float(item["delta_score"]), str(item["competency"])))
    return trends


def _derive_session_scores_from_questions(raw_questions: Any) -> dict[str, float]:
    if not isinstance(raw_questions, list):
        return {}

    totals: dict[str, float] = {}
    counts: dict[str, int] = {}

    for question in raw_questions:
        if not isinstance(question, dict):
            continue
        competency = _normalize_competency(question.get("competency"))
        score = _coerce_score(question.get("score"))
        if not competency or score is None:
            continue
        totals[competency] = totals.get(competency, 0.0) + score
        counts[competency] = counts.get(competency, 0) + 1

    derived: dict[str, float] = {}
    for competency in sorted(totals):
        count = counts.get(competency, 0)
        if count <= 0:
            continue
        derived[competency] = _round_score(totals[competency] / float(count))
    return derived


def _normalize_score_map(raw_map: Any) -> dict[str, float]:
    if not isinstance(raw_map, dict):
        return {}

    normalized: dict[str, float] = {}
    for raw_competency, raw_value in raw_map.items():
        competency = _normalize_competency(raw_competency)
        score = _coerce_score(raw_value)
        if not competency or score is None:
            continue
        normalized[competency] = score
    return normalized


def _normalize_competency(raw_value: Any) -> str:
    if not isinstance(raw_value, str):
        return ""
    value = raw_value.strip().lower()
    if not value:
        return ""
    if value.startswith("skill."):
        return value
    return f"skill.{value}"


def _coerce_score(raw_value: Any) -> float | None:
    try:
        value = float(raw_value)
    except (TypeError, ValueError):
        return None
    if value < 0.0:
        value = 0.0
    if value > 100.0:
        value = 100.0
    return _round_score(value)


def _round_score(value: float) -> float:
    return round(float(value), 2)


def _normalize_timestamp(raw_value: Any) -> str:
    if not isinstance(raw_value, str) or not raw_value.strip():
        return "1970-01-01T00:00:00+00:00"

    candidate = raw_value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        return "1970-01-01T00:00:00+00:00"

    if parsed.tzinfo is None:
        return parsed.isoformat() + "+00:00"
    return parsed.isoformat()
