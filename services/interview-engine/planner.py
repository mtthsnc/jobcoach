from __future__ import annotations

from dataclasses import dataclass
from typing import Any


DEFAULT_OPENING_QUESTION_COUNT = 3


@dataclass(frozen=True)
class RankedCompetency:
    competency: str
    source_competency: str
    ranking_position: int
    weight: float
    evidence_coverage: float
    deterministic_confidence: float


class DeterministicQuestionPlanner:
    """Deterministic opening-question planner for interview sessions."""

    def __init__(self, opening_question_count: int = DEFAULT_OPENING_QUESTION_COUNT) -> None:
        self._opening_question_count = max(1, min(5, int(opening_question_count)))

    def plan_opening_questions(
        self,
        *,
        session_id: str,
        job_spec: dict[str, Any],
        candidate_profile: dict[str, Any],
    ) -> list[dict[str, Any]]:
        ranked = _rank_competencies(job_spec=job_spec, candidate_profile=candidate_profile)
        session_suffix = session_id.split("_", 1)[1] if "_" in session_id else session_id

        questions: list[dict[str, Any]] = []
        for item in ranked[: self._opening_question_count]:
            difficulty = 2 if item.ranking_position <= 2 else 3
            questions.append(
                {
                    "question_id": f"q_{session_suffix}_{item.ranking_position}",
                    "text": _opening_question_text(item.competency, evidence_coverage=item.evidence_coverage),
                    "competency": item.competency,
                    "difficulty": difficulty,
                    "response": "",
                    "score": 0.0,
                    "planner_metadata": {
                        "source_competency": item.source_competency,
                        "ranking_position": item.ranking_position,
                        "deterministic_confidence": item.deterministic_confidence,
                    },
                }
            )

        return questions


def _rank_competencies(*, job_spec: dict[str, Any], candidate_profile: dict[str, Any]) -> list[RankedCompetency]:
    weight_map = _normalize_weight_map(job_spec.get("competency_weights"))
    evidence_map = _normalize_evidence_map(candidate_profile.get("skills"))

    if not weight_map and not evidence_map:
        return [
            RankedCompetency(
                competency="execution",
                source_competency="execution",
                ranking_position=1,
                weight=0.6,
                evidence_coverage=0.0,
                deterministic_confidence=0.718,
            )
        ]

    competency_pool = sorted(set(weight_map.keys()) | set(evidence_map.keys()))
    ranked_values: list[tuple[str, float, float, float]] = []
    for competency in competency_pool:
        weight = weight_map.get(competency)
        evidence_coverage = evidence_map.get(competency, 0.0)
        if weight is None:
            weight = round(0.45 + (0.35 * evidence_coverage), 3)

        coverage_gap = max(0.0, 1.0 - evidence_coverage)
        priority = round((weight * 0.7) + (coverage_gap * 0.3), 6)
        ranked_values.append((competency, priority, weight, evidence_coverage))

    ranked_values.sort(key=lambda item: (-item[1], -item[2], item[3], item[0]))

    ranked_competencies: list[RankedCompetency] = []
    for idx, (competency, _priority, weight, evidence_coverage) in enumerate(ranked_values, start=1):
        confidence = _deterministic_confidence(weight=weight, evidence_coverage=evidence_coverage, ranking_position=idx)
        ranked_competencies.append(
            RankedCompetency(
                competency=competency,
                source_competency=competency,
                ranking_position=idx,
                weight=weight,
                evidence_coverage=evidence_coverage,
                deterministic_confidence=confidence,
            )
        )

    return ranked_competencies


def _normalize_weight_map(raw_weights: Any) -> dict[str, float]:
    if not isinstance(raw_weights, dict):
        return {}

    normalized: dict[str, float] = {}
    max_weight = 0.0
    for raw_competency, raw_weight in raw_weights.items():
        competency = _normalize_competency(raw_competency)
        if not competency:
            continue
        try:
            value = float(raw_weight)
        except (TypeError, ValueError):
            continue
        if value <= 0.0:
            continue
        max_weight = max(max_weight, value)
        normalized[competency] = value

    if not normalized:
        return {}

    if max_weight <= 1.0:
        return {competency: round(min(1.0, value), 3) for competency, value in normalized.items()}
    return {competency: round(min(1.0, value / max_weight), 3) for competency, value in normalized.items()}


def _normalize_evidence_map(raw_skills: Any) -> dict[str, float]:
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
        normalized[competency] = round(max(0.0, min(1.0, value)), 3)
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


def _deterministic_confidence(*, weight: float, evidence_coverage: float, ranking_position: int) -> float:
    alignment = 1.0 - abs(weight - evidence_coverage)
    position_penalty = min(0.1, (ranking_position - 1) * 0.015)
    confidence = 0.52 + (weight * 0.28) + (alignment * 0.22) - position_penalty
    return round(max(0.5, min(0.99, confidence)), 3)


def _opening_question_text(competency: str, *, evidence_coverage: float) -> str:
    label = competency.replace("skill.", "").replace("_", " ").strip()
    if not label:
        label = "execution"

    if evidence_coverage <= 0.35:
        return f"Walk me through a time you built {label} capability from limited prior context."
    if evidence_coverage >= 0.75:
        return f"Tell me about your highest-impact example of applying {label} under pressure."
    return f"Tell me about a time you applied {label} to deliver a measurable outcome."
