from __future__ import annotations

import html
import re
import urllib.request
from dataclasses import dataclass
from typing import Protocol

SUPPORTED_SOURCE_TYPES = {"url", "text", "document_ref"}

# Canonical section ids used by downstream normalization/persistence stages.
HEADING_ALIASES: dict[str, tuple[str, ...]] = {
    "overview": (
        "overview",
        "summary",
        "role overview",
        "position overview",
        "about the role",
    ),
    "responsibilities": (
        "responsibilities",
        "what youll do",
        "what you will do",
        "what youll be doing",
        "your impact",
        "what youll own",
        "key responsibilities",
    ),
    "requirements": (
        "requirements",
        "qualifications",
        "required qualifications",
        "what were looking for",
        "what we are looking for",
        "must have",
    ),
    "preferred_qualifications": (
        "preferred qualifications",
        "nice to have",
        "bonus points",
        "preferred",
    ),
    "benefits": (
        "benefits",
        "perks",
        "what we offer",
        "compensation and benefits",
    ),
    "company": (
        "about us",
        "about company",
        "about the company",
        "company",
    ),
}


class ContentFetcher(Protocol):
    def fetch_url(self, url: str) -> str:
        ...

    def fetch_document_ref(self, ref: str) -> str:
        ...


class UrlContentFetcher:
    def fetch_url(self, url: str) -> str:
        request = urllib.request.Request(
            url,
            headers={"User-Agent": "jobcoach-job-extraction-worker/1.0"},
            method="GET",
        )
        with urllib.request.urlopen(request, timeout=15) as response:
            body = response.read()
            charset = response.headers.get_content_charset() or "utf-8"
        return body.decode(charset, errors="replace")

    def fetch_document_ref(self, ref: str) -> str:
        raise ValueError(f"document_ref source is not yet supported: {ref}")


@dataclass(frozen=True)
class ExtractedSection:
    section_id: str
    heading: str
    lines: tuple[str, ...]
    start_line: int
    end_line: int


@dataclass(frozen=True)
class ExtractedJobDocument:
    source_type: str
    source_value: str
    raw_text: str
    cleaned_text: str
    role_title: str
    sections: tuple[ExtractedSection, ...]


class JobExtractionWorker:
    def __init__(self, fetcher: ContentFetcher | None = None) -> None:
        self._fetcher = fetcher or UrlContentFetcher()

    def extract(self, *, source_type: str, source_value: str) -> ExtractedJobDocument:
        if source_type not in SUPPORTED_SOURCE_TYPES:
            raise ValueError(f"Unsupported source_type: {source_type}")
        if not source_value.strip():
            raise ValueError("source_value must be non-empty")

        raw_text = self._fetch_source(source_type=source_type, source_value=source_value)
        cleaned_text = clean_text(raw_text)
        cleaned_lines = [line for line in cleaned_text.split("\n") if line]
        role_title = _extract_role_title(cleaned_lines)
        sections = _segment_sections(cleaned_lines)

        return ExtractedJobDocument(
            source_type=source_type,
            source_value=source_value,
            raw_text=raw_text,
            cleaned_text=cleaned_text,
            role_title=role_title,
            sections=sections,
        )

    def _fetch_source(self, *, source_type: str, source_value: str) -> str:
        if source_type == "text":
            return source_value
        if source_type == "url":
            return self._fetcher.fetch_url(source_value)
        return self._fetcher.fetch_document_ref(source_value)


def clean_text(raw_text: str) -> str:
    text = raw_text.replace("\r\n", "\n").replace("\r", "\n")

    if _looks_like_html(text):
        text = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", text)
        text = re.sub(r"(?i)<br\s*/?>", "\n", text)
        text = re.sub(r"(?i)</(p|div|li|h1|h2|h3|h4|h5|h6|section|article)>", "\n", text)
        text = re.sub(r"(?is)<[^>]+>", " ", text)
        text = html.unescape(text)

    text = text.replace("\u2022", "- ").replace("•", "- ")
    text = text.replace("\u00a0", " ")

    cleaned_lines: list[str] = []
    for raw_line in text.split("\n"):
        line = raw_line.strip()
        if not line:
            continue
        line = re.sub(r"\s+", " ", line)
        line = re.sub(r"^[-*]\s*", "- ", line)
        cleaned_lines.append(line)

    return "\n".join(cleaned_lines)


def _segment_sections(cleaned_lines: list[str]) -> tuple[ExtractedSection, ...]:
    if not cleaned_lines:
        return tuple()

    sections: list[ExtractedSection] = []
    current_section_id = "overview"
    current_heading = "Overview"
    current_start = 1
    current_lines: list[str] = []

    for idx, line in enumerate(cleaned_lines, start=1):
        detected = _detect_heading(line)
        if detected is not None:
            if current_lines:
                sections.append(
                    ExtractedSection(
                        section_id=current_section_id,
                        heading=current_heading,
                        lines=tuple(current_lines),
                        start_line=current_start,
                        end_line=idx - 1,
                    )
                )
            current_section_id, canonical_heading = detected
            current_heading = canonical_heading
            current_start = idx
            current_lines = []
            continue

        current_lines.append(line)

    if current_lines:
        sections.append(
            ExtractedSection(
                section_id=current_section_id,
                heading=current_heading,
                lines=tuple(current_lines),
                start_line=current_start,
                end_line=len(cleaned_lines),
            )
        )

    return tuple(section for section in sections if section.lines)


def _extract_role_title(cleaned_lines: list[str]) -> str:
    if not cleaned_lines:
        return "Unknown Role"

    first_line = cleaned_lines[0]
    if _detect_heading(first_line) is None and not first_line.startswith("- ") and len(first_line.split()) <= 12:
        return first_line

    for line in cleaned_lines[:6]:
        match = re.match(r"(?i)^(role|position|job title)\s*[:\-]\s*(.+)$", line)
        if match:
            return match.group(2).strip()

    return "Unknown Role"


def _detect_heading(line: str) -> tuple[str, str] | None:
    token = _normalize_heading_token(line)
    if not token:
        return None

    for section_id, aliases in HEADING_ALIASES.items():
        if token in aliases:
            return section_id, _heading_for(section_id)

    if line.endswith(":"):
        token_without_colon = _normalize_heading_token(line[:-1])
        for section_id, aliases in HEADING_ALIASES.items():
            if token_without_colon in aliases:
                return section_id, _heading_for(section_id)

    return None


def _heading_for(section_id: str) -> str:
    return section_id.replace("_", " ").title()


def _normalize_heading_token(value: str) -> str:
    normalized = value.strip().lower().replace("'", "")
    normalized = re.sub(r"[^a-z0-9\s]", "", normalized)
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized.strip()


def _looks_like_html(text: str) -> bool:
    return bool(re.search(r"<\s*(html|body|p|div|section|article|h1|h2|h3|li|ul|ol)\b", text, flags=re.I))
