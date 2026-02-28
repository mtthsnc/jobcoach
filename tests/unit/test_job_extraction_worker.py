from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
WORKER_PATH = ROOT / "services" / "job-extraction" / "worker.py"
FIXTURE_DIR = ROOT / "tests" / "unit" / "fixtures" / "job_extraction"


def _load_worker_module():
    spec = importlib.util.spec_from_file_location("job_extraction_worker", WORKER_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load job extraction worker module: {WORKER_PATH}")

    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class _StubFetcher:
    def __init__(self, url_map: dict[str, str] | None = None, doc_map: dict[str, str] | None = None) -> None:
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


class JobExtractionWorkerBenchmarkTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.worker_module = _load_worker_module()

    def test_unsupported_source_type_fails_fast(self) -> None:
        worker = self.worker_module.JobExtractionWorker(fetcher=_StubFetcher())
        with self.assertRaises(ValueError):
            worker.extract(source_type="email", source_value="foo")

    def test_benchmark_corpus_sections(self) -> None:
        fixture_paths = sorted(FIXTURE_DIR.glob("benchmark_*.json"))
        self.assertGreater(len(fixture_paths), 0, "expected benchmark fixtures")

        for fixture_path in fixture_paths:
            case = json.loads(fixture_path.read_text(encoding="utf-8"))
            source_type = case["source_type"]
            source_value = case["source_value"]

            fetcher = _StubFetcher(
                url_map={source_value: case["fetched_content"]} if source_type == "url" else None,
                doc_map={source_value: case["fetched_content"]} if source_type == "document_ref" else None,
            )
            worker = self.worker_module.JobExtractionWorker(fetcher=fetcher)
            result = worker.extract(source_type=source_type, source_value=source_value)

            with self.subTest(case=case["case_id"]):
                self.assertEqual(result.role_title, case["expected_role_title"])

                section_ids = [section.section_id for section in result.sections]
                self.assertGreaterEqual(len(section_ids), int(case["min_sections"]))
                for expected_id in case["expected_sections"]:
                    self.assertIn(expected_id, section_ids)

                for section in result.sections:
                    self.assertGreater(len(section.lines), 0)
                    for line in section.lines:
                        self.assertEqual(line.strip(), line)

                if source_type == "url":
                    self.assertNotIn("<", result.cleaned_text)
                    self.assertNotIn(">", result.cleaned_text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
