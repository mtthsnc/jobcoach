from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
RUNNER_PATH = ROOT / "services" / "quality-eval" / "benchmark" / "candidate_parse_benchmark.py"


def _load_runner_module():
    spec = importlib.util.spec_from_file_location("candidate_parse_benchmark_runner", RUNNER_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load candidate parse benchmark runner module: {RUNNER_PATH}")

    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class CandidateParseBenchmarkRunnerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.module = _load_runner_module()

    def test_default_thresholds_pass(self) -> None:
        report, passed = self.module.run_benchmark()
        self.assertTrue(passed, report)
        self.assertTrue(report["passed"])
        self.assertGreater(len(report["cases"]), 0)
        self.assertGreaterEqual(report["aggregate"]["candidate_profile_valid_rate"], 0.95)
        self.assertGreaterEqual(report["aggregate"]["required_field_coverage"], 0.9)
        self.assertEqual(report["failed_thresholds"], [])

    def test_strict_thresholds_fail_with_failed_metrics(self) -> None:
        report, passed = self.module.run_benchmark(
            thresholds={
                "candidate_profile_valid_rate": 1.1,
                "required_field_coverage": 1.1,
                "story_quality_p50": 1.1,
                "story_quality_p10": 1.1,
            }
        )
        self.assertFalse(passed)
        self.assertFalse(report["passed"])
        failed_metrics = {entry["metric"] for entry in report["failed_thresholds"]}
        self.assertIn("candidate_profile_valid_rate", failed_metrics)
        self.assertIn("required_field_coverage", failed_metrics)
        self.assertIn("story_quality_p50", failed_metrics)
        self.assertIn("story_quality_p10", failed_metrics)

    def test_report_includes_story_quality_distribution_and_required_field_checks(self) -> None:
        report, _ = self.module.run_benchmark()
        distribution = report["story_quality_distribution"]
        self.assertIn("p10", distribution)
        self.assertIn("p50", distribution)
        self.assertIn("p90", distribution)
        self.assertGreater(distribution["count"], 0)

        first_case = report["cases"][0]
        self.assertIn("required_field_checks", first_case)
        self.assertIn("required_field_coverage", first_case)
        self.assertIn("story_quality_scores", first_case)
        self.assertIn("candidate_profile_valid", first_case)


if __name__ == "__main__":
    unittest.main(verbosity=2)
