from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
RUNNER_PATH = ROOT / "services" / "quality-eval" / "benchmark" / "trajectory_quality_benchmark.py"


def _load_runner_module():
    spec = importlib.util.spec_from_file_location("trajectory_quality_benchmark_runner", RUNNER_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load trajectory quality benchmark runner module: {RUNNER_PATH}")

    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class TrajectoryQualityBenchmarkRunnerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.module = _load_runner_module()

    def test_default_thresholds_pass(self) -> None:
        report, passed = self.module.run_benchmark()
        self.assertTrue(passed, report)
        self.assertTrue(report["passed"])
        self.assertGreater(len(report["cases"]), 0)
        self.assertGreaterEqual(report["aggregate"]["trend_metric_alignment_rate"], 1.0)
        self.assertGreaterEqual(report["aggregate"]["readiness_signal_alignment_rate"], 1.0)
        self.assertGreaterEqual(report["aggregate"]["trajectory_dashboard_consistency_rate"], 1.0)
        self.assertGreaterEqual(report["aggregate"]["trajectory_plan_structure_rate"], 1.0)
        self.assertGreaterEqual(report["aggregate"]["dashboard_schema_valid_rate"], 1.0)
        self.assertGreaterEqual(report["aggregate"]["overall_trajectory_quality"], 1.0)
        self.assertEqual(report["failed_thresholds"], [])

    def test_strict_thresholds_fail_with_failed_metrics(self) -> None:
        report, passed = self.module.run_benchmark(
            thresholds={
                "trend_metric_alignment_rate": 1.1,
                "readiness_signal_alignment_rate": 1.1,
                "trajectory_dashboard_consistency_rate": 1.1,
                "trajectory_plan_structure_rate": 1.1,
                "dashboard_schema_valid_rate": 1.1,
                "overall_trajectory_quality": 1.1,
            }
        )
        self.assertFalse(passed)
        self.assertFalse(report["passed"])
        failed_metrics = {entry["metric"] for entry in report["failed_thresholds"]}
        self.assertIn("trend_metric_alignment_rate", failed_metrics)
        self.assertIn("readiness_signal_alignment_rate", failed_metrics)
        self.assertIn("trajectory_dashboard_consistency_rate", failed_metrics)
        self.assertIn("trajectory_plan_structure_rate", failed_metrics)
        self.assertIn("dashboard_schema_valid_rate", failed_metrics)
        self.assertIn("overall_trajectory_quality", failed_metrics)

    def test_report_includes_trajectory_quality_fields(self) -> None:
        report, _ = self.module.run_benchmark()
        aggregate = report["aggregate"]
        self.assertIn("trend_metric_alignment_rate", aggregate)
        self.assertIn("readiness_signal_alignment_rate", aggregate)
        self.assertIn("trajectory_dashboard_consistency_rate", aggregate)
        self.assertIn("trajectory_plan_structure_rate", aggregate)
        self.assertIn("dashboard_schema_valid_rate", aggregate)
        self.assertIn("overall_trajectory_quality", aggregate)

        first_case = report["cases"][0]
        self.assertIn("generated_trajectory_plan", first_case)
        self.assertIn("dashboard_payload", first_case)
        self.assertIn("trend_metric_alignment_pass", first_case)
        self.assertIn("readiness_signal_alignment_pass", first_case)
        self.assertIn("trajectory_dashboard_consistency_pass", first_case)
        self.assertIn("trajectory_plan_structure_pass", first_case)
        self.assertIn("dashboard_schema_valid", first_case)
        self.assertIn("case_quality_score", first_case)


if __name__ == "__main__":
    unittest.main(verbosity=2)
