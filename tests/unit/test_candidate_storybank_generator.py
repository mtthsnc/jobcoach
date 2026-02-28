from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
GENERATOR_PATH = ROOT / "services" / "candidate-profile" / "storybank.py"
FIXTURE_DIR = ROOT / "tests" / "unit" / "fixtures" / "candidate_storybank"


def _load_module(module_name: str, module_path: Path):
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load module: {module_path}")

    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class CandidateStorybankGeneratorTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.module = _load_module("candidate_storybank_generator_test", GENERATOR_PATH)

    def test_fixture_cases_generate_storybank_with_quality_bounds(self) -> None:
        fixtures = sorted(FIXTURE_DIR.glob("*.json"))
        self.assertGreater(len(fixtures), 0)

        generator = self.module.CandidateStorybankGenerator()

        for fixture_path in fixtures:
            case = json.loads(fixture_path.read_text(encoding="utf-8"))
            stories = generator.generate(**case["input"])
            expectations = case.get("expectations", {})

            with self.subTest(case=case.get("case_id", fixture_path.name)):
                self.assertGreaterEqual(len(stories), int(expectations.get("min_story_count", 1)))

                has_metric = False
                found_any_required_competency = False
                required_competencies = set(expectations.get("required_competencies_any", []))

                for story in stories:
                    self.assertIsInstance(story.get("story_id"), str)
                    self.assertTrue(story["story_id"])
                    self.assertIsInstance(story.get("situation"), str)
                    self.assertTrue(story["situation"])
                    self.assertIsInstance(story.get("task"), str)
                    self.assertTrue(story["task"])
                    self.assertIsInstance(story.get("action"), str)
                    self.assertTrue(story["action"])
                    self.assertIsInstance(story.get("result"), str)
                    self.assertTrue(story["result"])

                    competencies = story.get("competencies")
                    self.assertIsInstance(competencies, list)
                    self.assertGreaterEqual(len(competencies), 1)
                    if required_competencies.intersection(set(competencies)):
                        found_any_required_competency = True

                    evidence_quality = float(story.get("evidence_quality"))
                    self.assertGreaterEqual(evidence_quality, 0.0)
                    self.assertLessEqual(evidence_quality, 1.0)

                    metrics = story.get("metrics")
                    if isinstance(metrics, list) and metrics:
                        has_metric = True

                self.assertTrue(found_any_required_competency)
                if bool(expectations.get("requires_metric", False)):
                    self.assertTrue(has_metric)


if __name__ == "__main__":
    unittest.main(verbosity=2)
