from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
RUNNER_PATH = ROOT / "services" / "quality-eval" / "benchmark" / "eval_orchestration_benchmark.py"


def _load_runner_module():
    spec = importlib.util.spec_from_file_location("eval_orchestration_benchmark_runner", RUNNER_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load eval orchestration benchmark runner module: {RUNNER_PATH}")

    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class EvalOrchestrationBenchmarkRunnerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.module = _load_runner_module()

    def test_default_thresholds_pass(self) -> None:
        report, passed = self.module.run_benchmark()
        self.assertTrue(passed, report)
        self.assertTrue(report["passed"])
        self.assertGreater(report["case_count"], 0)
        self.assertGreaterEqual(report["aggregate"]["transition_correctness_rate"], 1.0)
        self.assertGreaterEqual(report["aggregate"]["idempotency_correctness_rate"], 1.0)
        self.assertGreaterEqual(report["aggregate"]["lifecycle_event_integrity_rate"], 1.0)
        self.assertGreaterEqual(report["aggregate"]["overall_eval_orchestration_quality"], 1.0)
        self.assertEqual(report["failed_thresholds"], [])

    def test_strict_thresholds_fail_with_failed_metrics(self) -> None:
        report, passed = self.module.run_benchmark(
            thresholds={
                "transition_correctness_rate": 1.1,
                "idempotency_correctness_rate": 1.1,
                "lifecycle_event_integrity_rate": 1.1,
                "overall_eval_orchestration_quality": 1.1,
            }
        )
        self.assertFalse(passed)
        self.assertFalse(report["passed"])
        failed_metrics = {entry["metric"] for entry in report["failed_thresholds"]}
        self.assertIn("transition_correctness_rate", failed_metrics)
        self.assertIn("idempotency_correctness_rate", failed_metrics)
        self.assertIn("lifecycle_event_integrity_rate", failed_metrics)
        self.assertIn("overall_eval_orchestration_quality", failed_metrics)

    def test_report_includes_expected_case_fields(self) -> None:
        report, _ = self.module.run_benchmark()
        aggregate = report["aggregate"]
        self.assertIn("transition_correctness_rate", aggregate)
        self.assertIn("idempotency_correctness_rate", aggregate)
        self.assertIn("lifecycle_event_integrity_rate", aggregate)
        self.assertIn("overall_eval_orchestration_quality", aggregate)

        first_case = report["cases"][0]
        self.assertIn("suite", first_case)
        self.assertIn("conflict_suite", first_case)
        self.assertIn("terminal_status", first_case)
        self.assertIn("transition_pass", first_case)
        self.assertIn("idempotency_pass", first_case)
        self.assertIn("lifecycle_event_integrity_pass", first_case)
        self.assertIn("event_types", first_case)
        self.assertIn("event_count", first_case)
        self.assertIn("eval_run_row_count_for_idempotency_key", first_case)


if __name__ == "__main__":
    unittest.main(verbosity=2)
