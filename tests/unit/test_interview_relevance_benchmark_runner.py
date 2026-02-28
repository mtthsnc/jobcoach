from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
RUNNER_PATH = ROOT / "services" / "quality-eval" / "benchmark" / "interview_relevance_benchmark.py"


def _load_runner_module():
    spec = importlib.util.spec_from_file_location("interview_relevance_benchmark_runner", RUNNER_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load interview relevance benchmark runner module: {RUNNER_PATH}")

    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class InterviewRelevanceBenchmarkRunnerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.module = _load_runner_module()

    def test_default_thresholds_pass(self) -> None:
        report, passed = self.module.run_benchmark()
        self.assertTrue(passed, report)
        self.assertTrue(report["passed"])
        self.assertGreater(len(report["cases"]), 0)
        self.assertGreaterEqual(report["aggregate"]["opening_coverage"], 0.9)
        self.assertGreaterEqual(report["aggregate"]["followup_competency_alignment"], 0.9)
        self.assertGreaterEqual(report["aggregate"]["overall_relevance"], 0.9)
        self.assertEqual(report["failed_thresholds"], [])

    def test_strict_thresholds_fail_with_failed_metrics(self) -> None:
        report, passed = self.module.run_benchmark(
            thresholds={
                "opening_coverage": 1.1,
                "followup_competency_alignment": 1.1,
                "followup_reason_alignment": 1.1,
                "non_repetition_rate": 1.1,
                "difficulty_bound_rate": 1.1,
                "overall_relevance": 1.1,
            }
        )
        self.assertFalse(passed)
        self.assertFalse(report["passed"])
        failed_metrics = {entry["metric"] for entry in report["failed_thresholds"]}
        self.assertIn("opening_coverage", failed_metrics)
        self.assertIn("followup_competency_alignment", failed_metrics)
        self.assertIn("followup_reason_alignment", failed_metrics)
        self.assertIn("non_repetition_rate", failed_metrics)
        self.assertIn("difficulty_bound_rate", failed_metrics)
        self.assertIn("overall_relevance", failed_metrics)

    def test_report_includes_opening_and_followup_relevance_fields(self) -> None:
        report, _ = self.module.run_benchmark()
        aggregate = report["aggregate"]
        self.assertIn("opening_coverage", aggregate)
        self.assertIn("opening_order_alignment", aggregate)
        self.assertIn("followup_competency_alignment", aggregate)
        self.assertIn("followup_reason_alignment", aggregate)
        self.assertIn("non_repetition_rate", aggregate)
        self.assertIn("difficulty_bound_rate", aggregate)
        self.assertIn("overall_relevance", aggregate)

        first_case = report["cases"][0]
        self.assertIn("expected_opening_competencies", first_case)
        self.assertIn("predicted_opening_competencies", first_case)
        self.assertIn("opening_coverage", first_case)
        self.assertIn("followup_selected_competency", first_case)
        self.assertIn("followup_selected_reason", first_case)
        self.assertIn("followup_non_repetition_pass", first_case)
        self.assertIn("followup_difficulty_bound_pass", first_case)
        self.assertIn("case_relevance_score", first_case)


if __name__ == "__main__":
    unittest.main(verbosity=2)
