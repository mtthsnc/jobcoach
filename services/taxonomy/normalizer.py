from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


ROOT_DIR = Path(__file__).resolve().parents[2]
DEFAULT_MAPPING_PATH = ROOT_DIR / "services" / "taxonomy" / "mappings" / "skill_terms.json"


@dataclass(frozen=True)
class NormalizedTerm:
    input_term: str
    canonical_id: str
    canonical_label: str
    matched_alias: str | None
    confidence: float
    is_known: bool


class TaxonomyNormalizer:
    """Deterministic mapping-first normalizer for extraction-stage terms."""

    def __init__(self, alias_to_canonical: dict[str, tuple[str, str]]) -> None:
        self._alias_to_canonical = alias_to_canonical

    @classmethod
    def from_file(cls, mapping_path: Path = DEFAULT_MAPPING_PATH) -> "TaxonomyNormalizer":
        mapping_doc = json.loads(mapping_path.read_text(encoding="utf-8"))
        entries = mapping_doc.get("terms")
        if not isinstance(entries, list):
            raise ValueError("taxonomy mapping file must contain a 'terms' array")

        alias_map: dict[str, tuple[str, str]] = {}
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            canonical_id = str(entry.get("canonical_id", "")).strip()
            canonical_label = str(entry.get("canonical_label", "")).strip()
            aliases = entry.get("aliases", [])
            if not canonical_id or not canonical_label or not isinstance(aliases, list):
                continue

            for alias in aliases:
                token = _normalize_token(str(alias))
                if token:
                    alias_map[token] = (canonical_id, canonical_label)

        if not alias_map:
            raise ValueError("taxonomy mapping file produced no aliases")

        return cls(alias_to_canonical=alias_map)

    def normalize_term(self, term: str) -> NormalizedTerm:
        cleaned = term.strip()
        token = _normalize_token(cleaned)
        if token in self._alias_to_canonical:
            canonical_id, canonical_label = self._alias_to_canonical[token]
            return NormalizedTerm(
                input_term=cleaned,
                canonical_id=canonical_id,
                canonical_label=canonical_label,
                matched_alias=token,
                confidence=1.0,
                is_known=True,
            )

        return NormalizedTerm(
            input_term=cleaned,
            canonical_id=_freeform_skill_id(token),
            canonical_label=cleaned,
            matched_alias=None,
            confidence=0.0,
            is_known=False,
        )

    def normalize_terms(self, terms: Iterable[str]) -> tuple[NormalizedTerm, ...]:
        return tuple(self.normalize_term(term) for term in terms)


def normalize_job_requirement_terms(
    *,
    required_skills: Iterable[str],
    preferred_skills: Iterable[str],
    normalizer: TaxonomyNormalizer,
) -> dict[str, tuple[NormalizedTerm, ...]]:
    """Bridge helper for wiring extraction output into M1-004 JobSpec persistence."""

    return {
        "required": normalizer.normalize_terms(required_skills),
        "preferred": normalizer.normalize_terms(preferred_skills),
    }


def _normalize_token(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    normalized = normalized.encode("ascii", "ignore").decode("ascii")
    normalized = normalized.lower().strip()
    normalized = normalized.replace("&", " and ")
    normalized = re.sub(r"[^a-z0-9\s]+", " ", normalized)
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized.strip()


def _freeform_skill_id(token: str) -> str:
    safe = token or "unknown"
    slug = safe.replace(" ", "_")
    slug = re.sub(r"[^a-z0-9_]+", "_", slug)
    slug = re.sub(r"_+", "_", slug).strip("_")
    if not slug:
        slug = "unknown"
    digest = hashlib.sha1(safe.encode("utf-8")).hexdigest()[:8]
    return f"skill.freeform.{slug[:32]}_{digest}"
