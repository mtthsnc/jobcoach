from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
RUNNER_PATH = ROOT / "services" / "quality-eval" / "benchmark" / "feedback_quality_benchmark.py"


def _load_runner_module():
    spec = importlib.util.spec_from_file_location("feedback_quality_benchmark_runner", RUNNER_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load feedback quality benchmark runner module: {RUNNER_PATH}")

    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class FeedbackQualityBenchmarkRunnerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.module = _load_runner_module()

    def test_default_thresholds_pass(self) -> None:
        report, passed = self.module.run_benchmark()
        self.assertTrue(passed, report)
        self.assertTrue(report["passed"])
        self.assertGreater(len(report["cases"]), 0)
        self.assertGreaterEqual(report["aggregate"]["completeness_rate"], 0.95)
        self.assertGreaterEqual(report["aggregate"]["action_plan_coverage_rate"], 1.0)
        self.assertGreaterEqual(report["aggregate"]["overall_feedback_quality"], 0.9)
        self.assertEqual(report["failed_thresholds"], [])

    def test_strict_thresholds_fail_with_failed_metrics(self) -> None:
        report, passed = self.module.run_benchmark(
            thresholds={
                "completeness_rate": 1.1,
                "root_cause_alignment_rate": 1.1,
                "evidence_traceability_rate": 1.1,
                "rewrite_structure_rate": 1.1,
                "action_plan_coverage_rate": 1.1,
                "overall_feedback_quality": 1.1,
            }
        )
        self.assertFalse(passed)
        self.assertFalse(report["passed"])
        failed_metrics = {entry["metric"] for entry in report["failed_thresholds"]}
        self.assertIn("completeness_rate", failed_metrics)
        self.assertIn("root_cause_alignment_rate", failed_metrics)
        self.assertIn("evidence_traceability_rate", failed_metrics)
        self.assertIn("rewrite_structure_rate", failed_metrics)
        self.assertIn("action_plan_coverage_rate", failed_metrics)
        self.assertIn("overall_feedback_quality", failed_metrics)

    def test_report_includes_case_quality_fields(self) -> None:
        report, _ = self.module.run_benchmark()
        aggregate = report["aggregate"]
        self.assertIn("completeness_rate", aggregate)
        self.assertIn("root_cause_alignment_rate", aggregate)
        self.assertIn("evidence_traceability_rate", aggregate)
        self.assertIn("rewrite_structure_rate", aggregate)
        self.assertIn("action_plan_coverage_rate", aggregate)
        self.assertIn("overall_feedback_quality", aggregate)

        first_case = report["cases"][0]
        self.assertIn("top_gaps", first_case)
        self.assertIn("answer_rewrites", first_case)
        self.assertIn("action_plan_count", first_case)
        self.assertIn("root_cause_alignment_pass", first_case)
        self.assertIn("rewrite_structure_pass", first_case)
        self.assertIn("case_quality_score", first_case)


if __name__ == "__main__":
    unittest.main(verbosity=2)
