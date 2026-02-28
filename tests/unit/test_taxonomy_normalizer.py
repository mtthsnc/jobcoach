from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
NORMALIZER_PATH = ROOT / "services" / "taxonomy" / "normalizer.py"
CASES_PATH = ROOT / "tests" / "unit" / "fixtures" / "taxonomy" / "normalization_cases.json"


def _load_normalizer_module():
    spec = importlib.util.spec_from_file_location("taxonomy_normalizer", NORMALIZER_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load taxonomy normalizer module: {NORMALIZER_PATH}")

    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class TaxonomyNormalizerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.module = _load_normalizer_module()
        cls.normalizer = cls.module.TaxonomyNormalizer.from_file()

    def test_fixture_mapping_cases(self) -> None:
        cases = json.loads(CASES_PATH.read_text(encoding="utf-8"))
        self.assertGreater(len(cases), 0)

        for case in cases:
            result = self.normalizer.normalize_term(case["input"])
            with self.subTest(input=case["input"]):
                self.assertEqual(result.canonical_id, case["expected_id"])
                self.assertEqual(result.is_known, bool(case["known"]))
                if result.is_known:
                    self.assertEqual(result.confidence, 1.0)
                else:
                    self.assertEqual(result.confidence, 0.0)

    def test_requirement_bridge_helper(self) -> None:
        normalized = self.module.normalize_job_requirement_terms(
            required_skills=["Python", "SQL", "nonexistent skill"],
            preferred_skills=["event bus"],
            normalizer=self.normalizer,
        )

        self.assertEqual([t.canonical_id for t in normalized["required"]], ["skill.python", "skill.sql", "unknown"])
        self.assertEqual([t.canonical_id for t in normalized["preferred"]], ["skill.event_driven_architecture"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
