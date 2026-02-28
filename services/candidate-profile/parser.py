from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any


SKILL_KEYWORDS: dict[str, tuple[str, ...]] = {
    "python": ("python",),
    "sql": ("sql", "postgres", "mysql", "sqlite"),
    "system_design": ("system design", "distributed systems", "scalability"),
    "api_design": ("api", "rest", "graphql"),
    "cloud": ("aws", "gcp", "azure", "cloud"),
    "leadership": ("led", "leadership", "managed", "mentored"),
    "communication": ("stakeholder", "cross-functional", "communication"),
}


@dataclass(frozen=True)
class ParsedExperience:
    company: str
    title: str
    start_date: str
    end_date: str | None
    highlights: tuple[str, ...]


class CandidateProfileParser:
    """Deterministic parser for M2 candidate-profile extraction."""

    def parse(
        self,
        *,
        ingestion_id: str,
        candidate_id: str | None,
        cv_text: str | None,
        cv_document_ref: str | None,
        target_roles: list[str] | None,
        story_notes: list[str] | None,
    ) -> dict[str, Any]:
        resolved_candidate_id = candidate_id or _candidate_id_from_ingestion(ingestion_id)
        source_text = (cv_text or "").strip()
        if not source_text:
            source_text = f"Document reference: {cv_document_ref or 'unknown'}"

        lines = _clean_lines(source_text)
        summary, used_fallback_summary = _extract_summary(lines)
        experiences = _extract_experiences(lines)
        if not experiences:
            experiences = (_fallback_experience(lines),)

        skills = _extract_skills(lines, story_notes or [])
        parse_confidence = _parse_confidence(
            has_cv_text=bool(cv_text and cv_text.strip()),
            used_fallback_summary=used_fallback_summary,
            experience_count=len(experiences),
            skill_count=len(skills),
        )

        payload: dict[str, Any] = {
            "candidate_id": resolved_candidate_id,
            "summary": summary,
            "experience": [
                {
                    "company": experience.company,
                    "title": experience.title,
                    "start_date": experience.start_date,
                    "highlights": list(experience.highlights),
                }
                for experience in experiences
            ],
            "skills": skills,
            "parse_confidence": parse_confidence,
            "version": 1,
        }

        for idx, experience in enumerate(experiences):
            if experience.end_date:
                payload["experience"][idx]["end_date"] = experience.end_date

        clean_target_roles = [role.strip() for role in (target_roles or []) if isinstance(role, str) and role.strip()]
        if clean_target_roles:
            payload["target_roles"] = _unique_preserving_order(clean_target_roles)

        return payload


def _candidate_id_from_ingestion(ingestion_id: str) -> str:
    suffix = ingestion_id[4:] if ingestion_id.startswith("ing_") else ingestion_id
    return f"cand_{suffix}"


def _clean_lines(text: str) -> list[str]:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.strip() for line in normalized.split("\n")]
    return [line for line in lines if line]


def _extract_summary(lines: list[str]) -> tuple[str, bool]:
    heading_tokens = {"summary", "experience", "skills", "education", "projects"}
    for line in lines:
        lowered = line.lower().rstrip(":")
        if lowered in heading_tokens:
            continue
        if line.startswith("- "):
            continue
        return line, False
    return "Candidate profile summary unavailable.", True


def _extract_experiences(lines: list[str]) -> tuple[ParsedExperience, ...]:
    experiences: list[ParsedExperience] = []
    for line in lines:
        parsed = _parse_experience_line(line)
        if parsed is not None:
            experiences.append(parsed)
    return tuple(experiences)


def _parse_experience_line(line: str) -> ParsedExperience | None:
    pipe_match = re.match(r"^(?P<company>[^|]+)\|\s*(?P<title>[^|]+)\|\s*(?P<dates>.+)$", line)
    if pipe_match:
        start_date, end_date = _parse_date_range(pipe_match.group("dates"))
        return ParsedExperience(
            company=pipe_match.group("company").strip(),
            title=pipe_match.group("title").strip(),
            start_date=start_date,
            end_date=end_date,
            highlights=(f"Delivered impact while serving as {pipe_match.group('title').strip()}.",),
        )

    at_match = re.match(
        r"^(?P<title>.+?)\s+at\s+(?P<company>.+?)\s*\((?P<dates>[^)]+)\)$",
        line,
        flags=re.IGNORECASE,
    )
    if at_match:
        start_date, end_date = _parse_date_range(at_match.group("dates"))
        return ParsedExperience(
            company=at_match.group("company").strip(),
            title=at_match.group("title").strip(),
            start_date=start_date,
            end_date=end_date,
            highlights=(f"Owned outcomes for {at_match.group('company').strip()}.",),
        )

    return None


def _fallback_experience(lines: list[str]) -> ParsedExperience:
    highlights = [line for line in lines if len(line.split()) >= 4][:3]
    if not highlights:
        highlights = ["Experience details were not explicitly structured in the source text."]
    return ParsedExperience(
        company="Unknown Company",
        title="Professional Experience",
        start_date="2020-01-01",
        end_date=None,
        highlights=tuple(highlights),
    )


def _parse_date_range(value: str) -> tuple[str, str | None]:
    cleaned = value.strip()
    match = re.match(
        r"^(?P<start>\d{4}(?:[-/]\d{1,2})?)\s*(?:-|to|–|—)\s*(?P<end>\d{4}(?:[-/]\d{1,2})?|present|current|now)$",
        cleaned,
        flags=re.IGNORECASE,
    )
    if not match:
        single = _normalize_date_token(cleaned)
        return single or "2020-01-01", None

    start_date = _normalize_date_token(match.group("start")) or "2020-01-01"
    end_token = match.group("end").lower()
    if end_token in {"present", "current", "now"}:
        return start_date, None
    return start_date, _normalize_date_token(match.group("end"))


def _normalize_date_token(token: str) -> str | None:
    candidate = token.strip().replace("/", "-")
    year_month_match = re.match(r"^(?P<year>\d{4})-(?P<month>\d{1,2})$", candidate)
    if year_month_match:
        year = int(year_month_match.group("year"))
        month = int(year_month_match.group("month"))
        if 1 <= month <= 12:
            return f"{year:04d}-{month:02d}-01"

    year_match = re.match(r"^(?P<year>\d{4})$", candidate)
    if year_match:
        return f"{int(year_match.group('year')):04d}-01-01"

    try:
        parsed = datetime.fromisoformat(candidate)
        return parsed.date().isoformat()
    except ValueError:
        return None


def _extract_skills(lines: list[str], story_notes: list[str]) -> dict[str, float]:
    text_blob = " ".join(lines + story_notes).lower()
    scores: dict[str, float] = {}

    for skill_id, aliases in SKILL_KEYWORDS.items():
        occurrences = 0
        for alias in aliases:
            occurrences += len(re.findall(rf"(?<![a-z0-9]){re.escape(alias)}(?![a-z0-9])", text_blob))
        if occurrences <= 0:
            continue
        score = min(1.0, 0.55 + (0.12 * occurrences))
        scores[skill_id] = round(score, 3)

    if scores:
        return scores

    return {"generalist": 0.6}


def _parse_confidence(
    *,
    has_cv_text: bool,
    used_fallback_summary: bool,
    experience_count: int,
    skill_count: int,
) -> float:
    score = 0.5
    if has_cv_text:
        score += 0.2
    else:
        score += 0.08

    if not used_fallback_summary:
        score += 0.1
    if experience_count > 0:
        score += 0.1
    if skill_count > 1:
        score += 0.07

    return round(max(0.0, min(0.99, score)), 3)


def _unique_preserving_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            ordered.append(value)
    return ordered
