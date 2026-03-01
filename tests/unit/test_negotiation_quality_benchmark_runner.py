from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
RUNNER_PATH = ROOT / "services" / "quality-eval" / "benchmark" / "negotiation_quality_benchmark.py"


def _load_runner_module():
    spec = importlib.util.spec_from_file_location("negotiation_quality_benchmark_runner", RUNNER_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load negotiation quality benchmark runner module: {RUNNER_PATH}")

    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class NegotiationQualityBenchmarkRunnerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.module = _load_runner_module()

    def test_default_thresholds_pass(self) -> None:
        report, passed = self.module.run_benchmark()
        self.assertTrue(passed, report)
        self.assertTrue(report["passed"])
        self.assertGreater(len(report["cases"]), 0)
        self.assertGreaterEqual(report["aggregate"]["strategy_structure_quality_rate"], 1.0)
        self.assertGreaterEqual(report["aggregate"]["follow_up_cadence_quality_rate"], 1.0)
        self.assertGreaterEqual(report["aggregate"]["branch_action_boundedness_rate"], 1.0)
        self.assertGreaterEqual(report["aggregate"]["evidence_link_consistency_rate"], 1.0)
        self.assertGreaterEqual(report["aggregate"]["negotiation_plan_schema_valid_rate"], 1.0)
        self.assertGreaterEqual(report["aggregate"]["overall_negotiation_quality"], 1.0)
        self.assertEqual(report["failed_thresholds"], [])

    def test_strict_thresholds_fail_with_failed_metrics(self) -> None:
        report, passed = self.module.run_benchmark(
            thresholds={
                "strategy_structure_quality_rate": 1.1,
                "follow_up_cadence_quality_rate": 1.1,
                "branch_action_boundedness_rate": 1.1,
                "evidence_link_consistency_rate": 1.1,
                "negotiation_plan_schema_valid_rate": 1.1,
                "overall_negotiation_quality": 1.1,
            }
        )
        self.assertFalse(passed)
        self.assertFalse(report["passed"])
        failed_metrics = {entry["metric"] for entry in report["failed_thresholds"]}
        self.assertIn("strategy_structure_quality_rate", failed_metrics)
        self.assertIn("follow_up_cadence_quality_rate", failed_metrics)
        self.assertIn("branch_action_boundedness_rate", failed_metrics)
        self.assertIn("evidence_link_consistency_rate", failed_metrics)
        self.assertIn("negotiation_plan_schema_valid_rate", failed_metrics)
        self.assertIn("overall_negotiation_quality", failed_metrics)

    def test_report_includes_negotiation_quality_fields(self) -> None:
        report, _ = self.module.run_benchmark()
        aggregate = report["aggregate"]
        self.assertIn("strategy_structure_quality_rate", aggregate)
        self.assertIn("follow_up_cadence_quality_rate", aggregate)
        self.assertIn("branch_action_boundedness_rate", aggregate)
        self.assertIn("evidence_link_consistency_rate", aggregate)
        self.assertIn("negotiation_plan_schema_valid_rate", aggregate)
        self.assertIn("overall_negotiation_quality", aggregate)

        first_case = report["cases"][0]
        self.assertIn("negotiation_plan", first_case)
        self.assertIn("strategy_structure_quality_pass", first_case)
        self.assertIn("strategy_structure_details", first_case)
        self.assertIn("follow_up_cadence_quality_pass", first_case)
        self.assertIn("follow_up_cadence_details", first_case)
        self.assertIn("branch_action_boundedness_pass", first_case)
        self.assertIn("branch_action_boundedness_details", first_case)
        self.assertIn("evidence_link_consistency_pass", first_case)
        self.assertIn("evidence_link_consistency_details", first_case)
        self.assertIn("negotiation_plan_schema_valid", first_case)
        self.assertIn("case_quality_score", first_case)


if __name__ == "__main__":
    unittest.main(verbosity=2)
