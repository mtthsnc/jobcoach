from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
RUNNER_PATH = ROOT / "services" / "quality-eval" / "benchmark" / "extraction_benchmark.py"


def _load_runner_module():
    spec = importlib.util.spec_from_file_location("extraction_benchmark_runner", RUNNER_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load extraction benchmark runner module: {RUNNER_PATH}")

    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class ExtractionBenchmarkRunnerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.module = _load_runner_module()

    def test_default_thresholds_pass(self) -> None:
        report, passed = self.module.run_benchmark()
        self.assertTrue(passed, report)
        self.assertTrue(report["passed"])
        self.assertGreater(len(report["cases"]), 0)
        self.assertGreaterEqual(report["aggregate"]["jobspec_valid_rate"], 0.9)
        self.assertEqual(report["failed_thresholds"], [])

    def test_strict_thresholds_fail_with_failed_metrics(self) -> None:
        report, passed = self.module.run_benchmark(
            thresholds={
                "role_title_accuracy": 1.1,
                "section_coverage": 1.1,
                "skill_precision": 1.1,
                "skill_recall": 1.1,
                "jobspec_valid_rate": 1.1,
            }
        )
        self.assertFalse(passed)
        self.assertFalse(report["passed"])
        failed_metrics = {entry["metric"] for entry in report["failed_thresholds"]}
        self.assertIn("role_title_accuracy", failed_metrics)
        self.assertIn("section_coverage", failed_metrics)
        self.assertIn("skill_precision", failed_metrics)
        self.assertIn("skill_recall", failed_metrics)
        self.assertIn("jobspec_valid_rate", failed_metrics)

    def test_case_metrics_include_skill_mapping_fields(self) -> None:
        report, _ = self.module.run_benchmark()
        first_case = report["cases"][0]
        self.assertIn("expected_normalized_skill_ids", first_case)
        self.assertIn("predicted_normalized_skill_ids", first_case)
        self.assertIn("skill_precision", first_case)
        self.assertIn("skill_recall", first_case)
        self.assertIn("jobspec_valid", first_case)


if __name__ == "__main__":
    unittest.main(verbosity=2)

