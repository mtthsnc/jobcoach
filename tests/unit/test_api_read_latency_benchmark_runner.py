from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
RUNNER_PATH = ROOT / "services" / "quality-eval" / "benchmark" / "api_read_latency_benchmark.py"


def _load_runner_module():
    spec = importlib.util.spec_from_file_location("api_read_latency_benchmark_runner", RUNNER_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load API read latency benchmark runner module: {RUNNER_PATH}")

    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class APIReadLatencyBenchmarkRunnerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.module = _load_runner_module()

    def test_default_thresholds_pass(self) -> None:
        report, passed = self.module.run_benchmark()
        self.assertTrue(passed, report)
        self.assertTrue(report["passed"])
        self.assertGreater(report["case_count"], 0)
        self.assertGreater(report["sample_count"], 0)
        self.assertLessEqual(report["aggregate"]["read_path_p95_ms"], 400.0)
        self.assertEqual(report["aggregate"]["read_path_success_rate"], 1.0)
        self.assertEqual(report["failed_thresholds"], [])

    def test_strict_thresholds_fail_with_failed_metrics(self) -> None:
        report, passed = self.module.run_benchmark(
            thresholds={
                "read_path_p95_ms": -1.0,
                "read_path_success_rate": 1.1,
            }
        )
        self.assertFalse(passed)
        self.assertFalse(report["passed"])
        failed_metrics = {entry["metric"] for entry in report["failed_thresholds"]}
        self.assertIn("read_path_p95_ms", failed_metrics)
        self.assertIn("read_path_success_rate", failed_metrics)

    def test_report_includes_expected_case_fields(self) -> None:
        report, _ = self.module.run_benchmark()
        aggregate = report["aggregate"]
        self.assertIn("read_path_success_rate", aggregate)
        self.assertIn("read_path_p50_ms", aggregate)
        self.assertIn("read_path_p95_ms", aggregate)
        self.assertIn("read_path_max_ms", aggregate)
        self.assertIn("read_path_mean_ms", aggregate)

        first_case = report["cases"][0]
        self.assertIn("case_id", first_case)
        self.assertIn("path", first_case)
        self.assertIn("expected_status", first_case)
        self.assertIn("status_samples", first_case)
        self.assertIn("status_pass", first_case)
        self.assertIn("latency_ms", first_case)
        self.assertIn("p95", first_case["latency_ms"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
