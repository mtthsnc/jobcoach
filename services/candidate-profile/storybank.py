from __future__ import annotations

import re
from typing import Any


COMPETENCY_KEYWORDS: dict[str, tuple[str, ...]] = {
    "ownership": ("owned", "ownership", "led", "drove"),
    "problem_solving": ("solved", "debugged", "resolved", "improved", "optimized"),
    "execution": ("delivered", "shipped", "implemented", "built"),
    "communication": ("stakeholder", "cross-functional", "communicated", "aligned"),
    "leadership": ("mentored", "managed", "led", "coached"),
    "technical_depth": ("python", "sql", "api", "distributed", "architecture"),
}


class CandidateStorybankGenerator:
    """Deterministic STAR story generation for M2 storybank pipeline."""

    def generate(
        self,
        *,
        candidate_id: str,
        experiences: list[dict[str, Any]],
        story_notes: list[str] | None,
    ) -> list[dict[str, Any]]:
        notes = [note.strip() for note in (story_notes or []) if isinstance(note, str) and note.strip()]
        stories: list[dict[str, Any]] = []

        for idx, experience in enumerate(experiences):
            story = self._story_from_experience(candidate_id=candidate_id, index=idx, experience=experience, notes=notes)
            stories.append(story)

        if not stories:
            stories.append(
                self._fallback_story(candidate_id=candidate_id, notes=notes)
            )

        return stories

    def _story_from_experience(
        self,
        *,
        candidate_id: str,
        index: int,
        experience: dict[str, Any],
        notes: list[str],
    ) -> dict[str, Any]:
        company = str(experience.get("company") or "an organization").strip()
        title = str(experience.get("title") or "a technical role").strip()
        highlights = [str(item).strip() for item in experience.get("highlights", []) if str(item).strip()]
        highlight_text = " ".join(highlights)

        situation = f"Primary systems at {company} needed stronger reliability and delivery velocity."
        task = f"As {title}, deliver measurable improvements to core workflows."
        action = highlights[0] if highlights else f"Implemented pragmatic engineering improvements across critical systems at {company}."
        result = self._result_text(highlights=highlights, notes=notes)

        competencies = self._competencies_from_text(" ".join([situation, task, action, result, highlight_text] + notes))
        metrics = self._extract_metrics([action, result, highlight_text] + notes)
        evidence_quality = self._evidence_quality(action=action, result=result, metrics=metrics, competencies=competencies)

        story: dict[str, Any] = {
            "story_id": f"story_{candidate_id}_{index + 1}",
            "situation": situation,
            "task": task,
            "action": action,
            "result": result,
            "competencies": competencies,
            "evidence_quality": evidence_quality,
        }
        if metrics:
            story["metrics"] = metrics
        return story

    def _fallback_story(self, *, candidate_id: str, notes: list[str]) -> dict[str, Any]:
        note = notes[0] if notes else "Delivered consistent execution under evolving requirements."
        competencies = self._competencies_from_text(note)
        metrics = self._extract_metrics([note])
        return {
            "story_id": f"story_{candidate_id}_1",
            "situation": "The team needed dependable execution on critical priorities.",
            "task": "Deliver outcomes with limited ambiguity and changing constraints.",
            "action": note,
            "result": "Improved team throughput and stakeholder confidence.",
            "competencies": competencies,
            "evidence_quality": self._evidence_quality(
                action=note,
                result="Improved team throughput and stakeholder confidence.",
                metrics=metrics,
                competencies=competencies,
            ),
            **({"metrics": metrics} if metrics else {}),
        }

    def _result_text(self, *, highlights: list[str], notes: list[str]) -> str:
        candidates = highlights + notes
        for text in candidates:
            if _contains_metric(text):
                return text
        if highlights:
            return f"Completed delivery outcomes including: {highlights[0]}"
        if notes:
            return f"Delivered outcomes reflected in team notes: {notes[0]}"
        return "Delivered measurable improvements to reliability and execution quality."

    def _competencies_from_text(self, text: str) -> list[str]:
        lowered = text.lower()
        competencies: list[str] = []
        for competency, keywords in COMPETENCY_KEYWORDS.items():
            if any(keyword in lowered for keyword in keywords):
                competencies.append(competency)
        if competencies:
            return competencies
        return ["execution"]

    def _extract_metrics(self, text_segments: list[str]) -> list[str]:
        metrics: list[str] = []
        for segment in text_segments:
            normalized = segment.strip()
            if not normalized:
                continue
            if _contains_metric(normalized):
                metrics.append(normalized)
        return _unique_preserving_order(metrics)[:3]

    def _evidence_quality(self, *, action: str, result: str, metrics: list[str], competencies: list[str]) -> float:
        score = 0.5
        if len(action.split()) >= 6:
            score += 0.1
        if len(result.split()) >= 6:
            score += 0.1
        if metrics:
            score += 0.2
        if len(competencies) >= 2:
            score += 0.1
        return round(max(0.0, min(0.99, score)), 3)


def _contains_metric(text: str) -> bool:
    return bool(re.search(r"\b\d+(\.\d+)?%?\b", text))


def _unique_preserving_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            ordered.append(value)
    return ordered
