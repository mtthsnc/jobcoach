from __future__ import annotations

import html
import json
import os
import re
import subprocess
import urllib.request
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

SUPPORTED_SOURCE_TYPES = {"url", "text", "document_ref"}
ROOT_DIR = Path(__file__).resolve().parents[2]
DEFAULT_DEFUDDLE_SCRIPT = ROOT_DIR / "tools" / "defuddle" / "extract.mjs"
DEFAULT_DEFUDDLE_TIMEOUT_SECONDS = 20

# Canonical section ids used by downstream normalization/persistence stages.
HEADING_ALIASES: dict[str, tuple[str, ...]] = {
    "overview": (
        "overview",
        "summary",
        "role overview",
        "position overview",
        "about the role",
        "om rollen",
        "introduktion",
    ),
    "responsibilities": (
        "responsibilities",
        "what youll do",
        "what you will do",
        "what youll be doing",
        "your impact",
        "what youll own",
        "key responsibilities",
        "dine ansvarsområder",
        "ansvarsområder",
        "ansvarsomraader",
        "arbejdsopgaver",
    ),
    "requirements": (
        "requirements",
        "qualifications",
        "required qualifications",
        "what were looking for",
        "what we are looking for",
        "must have",
        "hvem er du",
        "din profil",
        "vi forestiller os",
        "du er ikke nødvendigvis udvikler men du",
        "du er ikke nodvendigvis udvikler men du",
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
        "det vi tilbyder",
        "vi tilbyder",
    ),
    "company": (
        "about us",
        "about company",
        "about the company",
        "company",
        "om virksomheden",
        "om os",
        "om myextensions",
    ),
    "application": (
        "application",
        "how to apply",
        "ansøgning",
        "ansoegning",
    ),
}


class ContentFetcher(Protocol):
    def fetch_url(self, url: str) -> str:
        ...

    def fetch_document_ref(self, ref: str) -> str:
        ...


class UrlContentFetcher:
    def __init__(
        self,
        *,
        prefer_defuddle: bool | None = None,
        defuddle_script: str | Path | None = None,
        node_binary: str | None = None,
    ) -> None:
        prefer = os.environ.get("JOBCOACH_USE_DEFUDDLE", "1")
        self._prefer_defuddle = prefer_defuddle if prefer_defuddle is not None else prefer != "0"
        self._defuddle_script = Path(defuddle_script) if defuddle_script is not None else DEFAULT_DEFUDDLE_SCRIPT
        self._node_binary = node_binary or os.environ.get("NODE_BINARY", "node")
        timeout_raw = os.environ.get("JOBCOACH_DEFUDDLE_TIMEOUT_SECONDS", str(DEFAULT_DEFUDDLE_TIMEOUT_SECONDS))
        try:
            self._defuddle_timeout_seconds = max(1, int(timeout_raw))
        except ValueError:
            self._defuddle_timeout_seconds = DEFAULT_DEFUDDLE_TIMEOUT_SECONDS

    def fetch_url(self, url: str) -> str:
        if self._prefer_defuddle:
            try:
                return self._fetch_url_with_defuddle(url)
            except Exception:
                # Fall back to urllib to keep ingestion functional if Node tooling is unavailable.
                pass

        return self._fetch_url_with_urllib(url)

    def _fetch_url_with_urllib(self, url: str) -> str:
        request = urllib.request.Request(
            url,
            headers={"User-Agent": "jobcoach-job-extraction-worker/1.0"},
            method="GET",
        )
        with urllib.request.urlopen(request, timeout=15) as response:
            body = response.read()
            charset = response.headers.get_content_charset() or "utf-8"
        return body.decode(charset, errors="replace")

    def _fetch_url_with_defuddle(self, url: str) -> str:
        completed = subprocess.run(
            [self._node_binary, str(self._defuddle_script), url],
            check=False,
            capture_output=True,
            text=True,
            timeout=self._defuddle_timeout_seconds,
        )
        if completed.returncode != 0:
            stderr = (completed.stderr or "").strip()
            raise RuntimeError(f"defuddle extraction failed: {stderr}")

        payload = json.loads(completed.stdout or "{}")
        if not isinstance(payload, dict):
            raise RuntimeError("defuddle extractor output must be a JSON object")

        title = str(payload.get("title") or "").strip()
        content = str(payload.get("content") or "").strip()
        if not title and not content:
            raise RuntimeError("defuddle extractor returned empty content")

        if title and content:
            return f"{title}\n{content}"
        return title or content

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

    cleaned_lines = _trim_job_board_boilerplate(cleaned_lines)

    return "\n".join(cleaned_lines)


def _trim_job_board_boilerplate(lines: list[str]) -> list[str]:
    if len(lines) < 80:
        return lines

    start_markers = (
        "responsibilities",
        "requirements",
        "qualifications",
        "about the role",
        "about this role",
        "dine ansvarsområder",
        "hvem er du",
        "det vi tilbyder",
    )
    footer_markers = (
        "cookie",
        "privacy",
        "persondatapolitik",
        "betingelser",
        "©",
        "support for jobsøgere",
        "support for arbejdsgivere",
    )

    start_idx = 0
    for idx, line in enumerate(lines):
        normalized = line.lower()
        if any(marker in normalized for marker in start_markers):
            if idx > 15:
                start_idx = idx - 1
            break

    trimmed = lines[start_idx:] if start_idx else list(lines)

    end_idx = len(trimmed)
    for idx, line in enumerate(trimmed):
        normalized = line.lower()
        if any(marker in normalized for marker in footer_markers):
            if idx > 20:
                end_idx = idx
            break

    return trimmed[:end_idx]


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
        alias_tokens = {alias for alias in aliases}
        alias_tokens.update(_normalize_heading_token(alias) for alias in aliases)
        if token in alias_tokens:
            return section_id, _heading_for(section_id)

    if line.endswith(":"):
        token_without_colon = _normalize_heading_token(line[:-1])
        for section_id, aliases in HEADING_ALIASES.items():
            alias_tokens = {alias for alias in aliases}
            alias_tokens.update(_normalize_heading_token(alias) for alias in aliases)
            if token_without_colon in alias_tokens:
                return section_id, _heading_for(section_id)

    return None


def _heading_for(section_id: str) -> str:
    return section_id.replace("_", " ").title()


def _normalize_heading_token(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    normalized = normalized.encode("ascii", "ignore").decode("ascii")
    normalized = normalized.strip().lower().replace("'", "")
    normalized = re.sub(r"[^a-z0-9\s]", "", normalized)
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized.strip()


def _looks_like_html(text: str) -> bool:
    return bool(re.search(r"<\s*(html|body|p|div|section|article|h1|h2|h3|li|ul|ol)\b", text, flags=re.I))
