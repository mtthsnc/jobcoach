#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT_DIR = Path(__file__).resolve().parents[3]
WORKER_PATH = ROOT_DIR / "services" / "job-extraction" / "worker.py"
NORMALIZER_PATH = ROOT_DIR / "services" / "taxonomy" / "normalizer.py"
VALIDATOR_PATH = ROOT_DIR / "services" / "quality-eval" / "schema_validation" / "validator.py"
FIXTURE_DIR = ROOT_DIR / "tests" / "unit" / "fixtures" / "job_extraction"
DEFAULT_REPORT_PATH = ROOT_DIR / ".tmp" / "extraction-benchmark-report.json"

DEFAULT_THRESHOLDS = {
    "role_title_accuracy": 0.90,
    "section_coverage": 0.90,
    "skill_precision": 0.80,
    "skill_recall": 0.80,
    "jobspec_valid_rate": 0.90,
}

if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

REQUIREMENTS_SECTION_IDS = {"requirements", "preferred_qualifications"}
SKILL_TOKEN_PATTERN = re.compile(r"[^a-z0-9\s]+")
SKILL_SPACE_PATTERN = re.compile(r"\s+")


@dataclass(frozen=True)
class BenchmarkCase:
    case_id: str
    source_type: str
    source_value: str
    expected_role_title: str
    expected_sections: tuple[str, ...]
    min_sections: int
    expected_normalized_skill_ids: tuple[str, ...]
    fetched_content: str | None


class _StubFetcher:
    def __init__(self, *, url_map: dict[str, str] | None = None, doc_map: dict[str, str] | None = None) -> None:
        self._url_map = url_map or {}
        self._doc_map = doc_map or {}

    def fetch_url(self, url: str) -> str:
        if url not in self._url_map:
            raise ValueError(f"unexpected url fetch: {url}")
        return self._url_map[url]

    def fetch_document_ref(self, ref: str) -> str:
        if ref not in self._doc_map:
            raise ValueError(f"unexpected document_ref fetch: {ref}")
        return self._doc_map[ref]


def _load_module(module_name: str, module_path: Path):
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load module: {module_path}")

    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _load_benchmark_cases(fixtures_dir: Path) -> list[BenchmarkCase]:
    fixture_paths = sorted(fixtures_dir.glob("benchmark_*.json"))
    if not fixture_paths:
        raise RuntimeError(f"No benchmark fixtures found under {fixtures_dir}")

    cases: list[BenchmarkCase] = []
    for fixture_path in fixture_paths:
        raw_case = json.loads(fixture_path.read_text(encoding="utf-8"))
        case = BenchmarkCase(
            case_id=str(raw_case["case_id"]),
            source_type=str(raw_case["source_type"]),
            source_value=str(raw_case["source_value"]),
            expected_role_title=str(raw_case["expected_role_title"]),
            expected_sections=tuple(str(value) for value in raw_case.get("expected_sections", [])),
            min_sections=int(raw_case.get("min_sections", 0)),
            expected_normalized_skill_ids=tuple(str(value) for value in raw_case.get("expected_normalized_skill_ids", [])),
            fetched_content=str(raw_case["fetched_content"]) if "fetched_content" in raw_case else None,
        )
        cases.append(case)
    return cases


def _section_lines_by_id(sections: tuple[Any, ...]) -> dict[str, list[str]]:
    grouped: dict[str, list[str]] = {}
    for section in sections:
        section_id = str(getattr(section, "section_id", "")).strip()
        lines = getattr(section, "lines", ())
        if not section_id:
            continue
        clean_lines = [_clean_line(str(line)) for line in lines if _clean_line(str(line))]
        if clean_lines:
            grouped.setdefault(section_id, []).extend(clean_lines)
    return grouped


def _clean_line(value: str) -> str:
    line = value.strip()
    line = re.sub(r"^[-*]\s*", "", line)
    return line.strip()


def _extract_normalized_skill_ids(lines: list[str], normalizer: Any) -> list[str]:
    alias_map = getattr(normalizer, "_alias_to_canonical", {})
    aliases = sorted([alias for alias in alias_map if isinstance(alias, str) and alias], key=len, reverse=True)

    matched: list[str] = []
    for line in lines:
        normalized_line = SKILL_TOKEN_PATTERN.sub(" ", line.lower())
        normalized_line = SKILL_SPACE_PATTERN.sub(" ", normalized_line).strip()
        for alias in aliases:
            if re.search(rf"(^|\s){re.escape(alias)}(\s|$)", normalized_line):
                canonical = alias_map.get(alias)
                if isinstance(canonical, tuple) and len(canonical) >= 1:
                    matched.append(str(canonical[0]))
    return _unique_preserving_order(matched)


def _canonical_label_lookup(normalizer: Any) -> dict[str, str]:
    alias_map = getattr(normalizer, "_alias_to_canonical", {})
    labels: dict[str, str] = {}
    for value in alias_map.values():
        if isinstance(value, tuple) and len(value) >= 2:
            labels[str(value[0])] = str(value[1])
    return labels


def _build_jobspec_payload(
    *,
    benchmark_case: BenchmarkCase,
    extracted: Any,
    section_lines: dict[str, list[str]],
    required_skill_ids: list[str],
    preferred_skill_ids: list[str],
    canonical_labels: dict[str, str],
) -> dict[str, Any]:
    responsibilities = section_lines.get("responsibilities", []) or section_lines.get("overview", [])
    if not responsibilities:
        responsibilities = [str(getattr(extracted, "role_title", "Unknown Role"))]

    required_skill_labels = [canonical_labels.get(skill_id, skill_id) for skill_id in required_skill_ids]
    preferred_skill_labels = [canonical_labels.get(skill_id, skill_id) for skill_id in preferred_skill_ids]

    competency_weights: dict[str, float] = {}
    for skill_id in required_skill_ids:
        competency_weights[skill_id] = 1.0
    for skill_id in preferred_skill_ids:
        competency_weights[skill_id] = max(competency_weights.get(skill_id, 0.0), 0.65)

    evidence_spans = [
        {
            "field": f"responsibilities[{idx}]",
            "text": text,
            "confidence": 0.85,
        }
        for idx, text in enumerate(responsibilities)
    ]

    payload = {
        "job_spec_id": f"benchmark_{benchmark_case.case_id}",
        "source": {
            "type": benchmark_case.source_type,
            "value": benchmark_case.source_value,
            "captured_at": "2026-02-28T00:00:00Z",
        },
        "role_title": str(getattr(extracted, "role_title", "Unknown Role")),
        "responsibilities": responsibilities,
        "requirements": {
            "required_skills": required_skill_labels,
            "preferred_skills": preferred_skill_labels,
        },
        "competency_weights": competency_weights,
        "evidence_spans": evidence_spans,
        "extraction_confidence": 0.90,
        "taxonomy_version": "m1-taxonomy-v1",
        "version": 1,
    }
    return payload


def _skill_precision(predicted: set[str], expected: set[str]) -> float:
    if not predicted:
        return 1.0 if not expected else 0.0
    return len(predicted.intersection(expected)) / len(predicted)


def _skill_recall(predicted: set[str], expected: set[str]) -> float:
    if not expected:
        return 1.0
    return len(predicted.intersection(expected)) / len(expected)


def _mean(values: list[float]) -> float:
    if not values:
        return 0.0
    return sum(values) / len(values)


def _unique_preserving_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            ordered.append(value)
    return ordered


def run_benchmark(
    *,
    fixtures_dir: Path = FIXTURE_DIR,
    thresholds: dict[str, float] | None = None,
) -> tuple[dict[str, Any], bool]:
    active_thresholds = dict(DEFAULT_THRESHOLDS)
    if thresholds:
        active_thresholds.update(thresholds)

    worker_module = _load_module("job_extraction_worker_benchmark", WORKER_PATH)
    normalizer_module = _load_module("taxonomy_normalizer_benchmark", NORMALIZER_PATH)
    validator_module = _load_module("core_schema_validator_benchmark", VALIDATOR_PATH)

    cases = _load_benchmark_cases(fixtures_dir)
    normalizer = normalizer_module.TaxonomyNormalizer.from_file()
    validator = validator_module.CoreSchemaValidator.from_file()
    canonical_labels = _canonical_label_lookup(normalizer)

    case_reports: list[dict[str, Any]] = []
    role_title_scores: list[float] = []
    section_coverage_scores: list[float] = []
    skill_precision_scores: list[float] = []
    skill_recall_scores: list[float] = []
    jobspec_valid_scores: list[float] = []

    for benchmark_case in cases:
        fetcher = _StubFetcher(
            url_map={benchmark_case.source_value: benchmark_case.fetched_content}
            if benchmark_case.source_type == "url" and benchmark_case.fetched_content is not None
            else None,
            doc_map={benchmark_case.source_value: benchmark_case.fetched_content}
            if benchmark_case.source_type == "document_ref" and benchmark_case.fetched_content is not None
            else None,
        )
        worker = worker_module.JobExtractionWorker(fetcher=fetcher)
        extracted = worker.extract(source_type=benchmark_case.source_type, source_value=benchmark_case.source_value)

        detected_section_ids = [str(section.section_id) for section in extracted.sections]
        expected_sections = list(benchmark_case.expected_sections)
        expected_section_set = set(expected_sections)
        detected_section_set = set(detected_section_ids)
        matched_sections = sorted(expected_section_set.intersection(detected_section_set))
        section_coverage = (
            len(matched_sections) / len(expected_section_set)
            if expected_section_set
            else 1.0
        )
        min_sections_met = len(detected_section_ids) >= benchmark_case.min_sections

        section_lines = _section_lines_by_id(extracted.sections)
        requirements_lines: list[str] = []
        for section_id in REQUIREMENTS_SECTION_IDS:
            requirements_lines.extend(section_lines.get(section_id, []))

        predicted_skill_ids = _extract_normalized_skill_ids(requirements_lines, normalizer)
        expected_skill_ids = list(benchmark_case.expected_normalized_skill_ids)
        predicted_skill_set = set(predicted_skill_ids)
        expected_skill_set = set(expected_skill_ids)
        precision = _skill_precision(predicted_skill_set, expected_skill_set)
        recall = _skill_recall(predicted_skill_set, expected_skill_set)

        required_skill_ids = _extract_normalized_skill_ids(section_lines.get("requirements", []), normalizer)
        preferred_skill_ids = _extract_normalized_skill_ids(section_lines.get("preferred_qualifications", []), normalizer)
        jobspec_payload = _build_jobspec_payload(
            benchmark_case=benchmark_case,
            extracted=extracted,
            section_lines=section_lines,
            required_skill_ids=required_skill_ids,
            preferred_skill_ids=preferred_skill_ids,
            canonical_labels=canonical_labels,
        )
        validation = validator.validate("JobSpec", jobspec_payload)
        jobspec_valid = validation.is_valid

        role_title_match = extracted.role_title == benchmark_case.expected_role_title
        role_title_score = 1.0 if role_title_match else 0.0
        jobspec_valid_score = 1.0 if jobspec_valid else 0.0

        role_title_scores.append(role_title_score)
        section_coverage_scores.append(section_coverage)
        skill_precision_scores.append(precision)
        skill_recall_scores.append(recall)
        jobspec_valid_scores.append(jobspec_valid_score)

        case_reports.append(
            {
                "case_id": benchmark_case.case_id,
                "source_type": benchmark_case.source_type,
                "role_title_expected": benchmark_case.expected_role_title,
                "role_title_predicted": extracted.role_title,
                "role_title_match": role_title_match,
                "expected_sections": expected_sections,
                "detected_sections": detected_section_ids,
                "section_coverage": round(section_coverage, 3),
                "min_sections": benchmark_case.min_sections,
                "detected_section_count": len(detected_section_ids),
                "min_sections_met": min_sections_met,
                "expected_normalized_skill_ids": expected_skill_ids,
                "predicted_normalized_skill_ids": predicted_skill_ids,
                "skill_precision": round(precision, 3),
                "skill_recall": round(recall, 3),
                "jobspec_valid": jobspec_valid,
                "jobspec_validation_issues": [
                    {"path": issue.path, "message": issue.message}
                    for issue in validation.issues
                ],
            }
        )

    aggregate = {
        "role_title_accuracy": round(_mean(role_title_scores), 3),
        "section_coverage": round(_mean(section_coverage_scores), 3),
        "skill_precision": round(_mean(skill_precision_scores), 3),
        "skill_recall": round(_mean(skill_recall_scores), 3),
        "jobspec_valid_rate": round(_mean(jobspec_valid_scores), 3),
    }

    failed_thresholds: list[dict[str, Any]] = []
    for metric_name, threshold in active_thresholds.items():
        actual = float(aggregate.get(metric_name, 0.0))
        if actual < threshold:
            failed_thresholds.append(
                {
                    "metric": metric_name,
                    "actual": round(actual, 3),
                    "threshold": round(float(threshold), 3),
                }
            )

    passed = len(failed_thresholds) == 0
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "fixtures_dir": str(fixtures_dir),
        "thresholds": {name: round(float(value), 3) for name, value in active_thresholds.items()},
        "aggregate": aggregate,
        "failed_thresholds": failed_thresholds,
        "passed": passed,
        "cases": case_reports,
    }
    return report, passed


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run deterministic extraction benchmark quality gate.")
    parser.add_argument("--fixtures-dir", default=str(FIXTURE_DIR), help="Directory containing benchmark_*.json fixtures")
    parser.add_argument("--report-path", default=str(DEFAULT_REPORT_PATH), help="Path to write JSON benchmark report")
    parser.add_argument("--min-role-title-accuracy", type=float, default=DEFAULT_THRESHOLDS["role_title_accuracy"])
    parser.add_argument("--min-section-coverage", type=float, default=DEFAULT_THRESHOLDS["section_coverage"])
    parser.add_argument("--min-skill-precision", type=float, default=DEFAULT_THRESHOLDS["skill_precision"])
    parser.add_argument("--min-skill-recall", type=float, default=DEFAULT_THRESHOLDS["skill_recall"])
    parser.add_argument("--min-jobspec-valid-rate", type=float, default=DEFAULT_THRESHOLDS["jobspec_valid_rate"])
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    report, passed = run_benchmark(
        fixtures_dir=Path(args.fixtures_dir),
        thresholds={
            "role_title_accuracy": args.min_role_title_accuracy,
            "section_coverage": args.min_section_coverage,
            "skill_precision": args.min_skill_precision,
            "skill_recall": args.min_skill_recall,
            "jobspec_valid_rate": args.min_jobspec_valid_rate,
        },
    )

    report_path = Path(args.report_path)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
