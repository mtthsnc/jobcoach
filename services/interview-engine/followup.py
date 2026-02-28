from __future__ import annotations

from typing import Any


LOW_SCORE_REMEDIATION_THRESHOLD = 62.0
TARGET_SCORE_THRESHOLD = 75.0
MAX_REPEAT_PER_COMPETENCY = 2


class AdaptiveFollowupSelector:
    """Deterministic follow-up selector based on prior score and competency gaps."""

    def select_followup(
        self,
        *,
        questions: list[dict[str, Any]],
        scores: dict[str, float],
        last_question: dict[str, Any],
        last_score: float,
    ) -> dict[str, Any]:
        counts = _competency_counts(questions)
        current_competency = _normalized_competency(last_question.get("competency"))
        last_difficulty = _difficulty(last_question.get("difficulty"))
        ranking_map = _ranking_map(questions)

        if (
            current_competency
            and float(last_score) < LOW_SCORE_REMEDIATION_THRESHOLD
            and counts.get(current_competency, 0) < MAX_REPEAT_PER_COMPETENCY
        ):
            return {
                "competency": current_competency,
                "reason": "low_score_remediation",
                "difficulty": min(5, last_difficulty + 1),
                "ranking_position": ranking_map.get(current_competency, 1),
                "confidence": _confidence_for_remediation(
                    score=float(last_score),
                    ranking_position=ranking_map.get(current_competency, 1),
                ),
            }

        gap_candidates = _rank_gap_candidates(
            questions=questions,
            scores=scores,
            ranking_map=ranking_map,
            exclude_competency=current_competency,
        )
        if gap_candidates:
            selected = gap_candidates[0]
            return {
                "competency": selected["competency"],
                "reason": "coverage_gap",
                "difficulty": min(5, last_difficulty + 1),
                "ranking_position": int(selected["ranking_position"]),
                "confidence": _confidence_for_gap(
                    priority=float(selected["priority"]),
                    ranking_position=int(selected["ranking_position"]),
                ),
            }

        fallback_competency = _fallback_competency(questions=questions, exclude_competency=current_competency)
        fallback_rank = ranking_map.get(fallback_competency, max(1, len(ranking_map) + 1))
        reason = "coverage_extension" if fallback_competency != current_competency else "stabilize_signal"
        return {
            "competency": fallback_competency,
            "reason": reason,
            "difficulty": min(5, last_difficulty + 1),
            "ranking_position": fallback_rank,
            "confidence": _confidence_for_gap(
                priority=0.52,
                ranking_position=fallback_rank,
            ),
        }


def _rank_gap_candidates(
    *,
    questions: list[dict[str, Any]],
    scores: dict[str, float],
    ranking_map: dict[str, int],
    exclude_competency: str,
) -> list[dict[str, Any]]:
    competencies = _unique_competencies(questions)
    candidates: list[dict[str, Any]] = []
    for competency in competencies:
        if competency == exclude_competency:
            continue
        answered_count = _answered_count_for_competency(questions=questions, competency=competency)
        mean_score = float(scores.get(competency, 0.0))

        gap_score = 1.0 - max(0.0, min(1.0, mean_score / 100.0))
        if answered_count == 0:
            gap_score = max(gap_score, 0.72)

        if answered_count > 0 and mean_score >= TARGET_SCORE_THRESHOLD:
            gap_score *= 0.65

        ranking_position = int(ranking_map.get(competency, max(1, len(ranking_map) + 1)))
        rank_weight = 1.0 / float(max(1, ranking_position))
        priority = round((gap_score * 0.72) + (rank_weight * 0.28), 6)
        candidates.append(
            {
                "competency": competency,
                "priority": priority,
                "ranking_position": ranking_position,
            }
        )

    candidates.sort(key=lambda item: (-float(item["priority"]), int(item["ranking_position"]), str(item["competency"])))
    return candidates


def _competency_counts(questions: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for question in questions:
        competency = _normalized_competency(question.get("competency"))
        counts[competency] = counts.get(competency, 0) + 1
    return counts


def _unique_competencies(questions: list[dict[str, Any]]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for question in questions:
        competency = _normalized_competency(question.get("competency"))
        if competency and competency not in seen:
            seen.add(competency)
            ordered.append(competency)
    return ordered or ["execution"]


def _ranking_map(questions: list[dict[str, Any]]) -> dict[str, int]:
    ranking: dict[str, int] = {}
    for idx, question in enumerate(questions, start=1):
        competency = _normalized_competency(question.get("competency"))
        metadata = question.get("planner_metadata")
        from_metadata = None
        if isinstance(metadata, dict):
            ranking_value = metadata.get("ranking_position")
            if isinstance(ranking_value, int) and ranking_value >= 1:
                from_metadata = ranking_value
        ranking.setdefault(competency, from_metadata if from_metadata is not None else idx)
    return ranking


def _answered_count_for_competency(*, questions: list[dict[str, Any]], competency: str) -> int:
    count = 0
    for question in questions:
        if _normalized_competency(question.get("competency")) != competency:
            continue
        if str(question.get("response", "")).strip():
            count += 1
    return count


def _fallback_competency(*, questions: list[dict[str, Any]], exclude_competency: str) -> str:
    for competency in _unique_competencies(questions):
        if competency != exclude_competency:
            return competency
    return exclude_competency or "execution"


def _confidence_for_remediation(*, score: float, ranking_position: int) -> float:
    rank_factor = 1.0 / float(max(1, ranking_position))
    recovery_signal = max(0.0, min(1.0, (LOW_SCORE_REMEDIATION_THRESHOLD - score) / 100.0))
    confidence = 0.62 + (rank_factor * 0.12) + (recovery_signal * 0.26)
    return round(max(0.5, min(0.99, confidence)), 3)


def _confidence_for_gap(*, priority: float, ranking_position: int) -> float:
    rank_factor = 1.0 / float(max(1, ranking_position))
    confidence = 0.54 + (max(0.0, min(1.0, priority)) * 0.28) + (rank_factor * 0.12)
    return round(max(0.5, min(0.99, confidence)), 3)


def _normalized_competency(value: Any) -> str:
    if not isinstance(value, str):
        return "execution"
    normalized = value.strip()
    return normalized or "execution"


def _difficulty(raw_value: Any) -> int:
    try:
        return max(1, min(5, int(raw_value)))
    except (TypeError, ValueError):
        return 1
