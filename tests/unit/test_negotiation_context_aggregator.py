from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
AGGREGATOR_PATH = ROOT / "services" / "negotiation-planning" / "aggregator.py"
FIXTURE_DIR = ROOT / "tests" / "unit" / "fixtures" / "negotiation_context"


def _load_aggregator_module():
    spec = importlib.util.spec_from_file_location("negotiation_context_aggregator", AGGREGATOR_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load negotiation context aggregator module: {AGGREGATOR_PATH}")

    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _load_fixture(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


class NegotiationContextAggregatorTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        module = _load_aggregator_module()
        cls.aggregator = module.DeterministicNegotiationContextAggregator()

    def test_fixture_cases_are_deterministic_with_stable_ordering_and_math(self) -> None:
        fixture_paths = sorted(FIXTURE_DIR.glob("benchmark_*.json"))
        self.assertGreater(len(fixture_paths), 0, "expected negotiation context fixtures")

        for fixture_path in fixture_paths:
            case = _load_fixture(fixture_path)
            with self.subTest(case=case.get("case_id", fixture_path.name)):
                first = self.aggregator.aggregate(
                    candidate_id=str(case["candidate_id"]),
                    target_role=str(case["target_role"]),
                    request_payload=dict(case.get("request_payload", {})),
                    candidate_profile=dict(case.get("candidate_profile", {})),
                    interview_sessions=[entry for entry in case.get("interview_sessions", []) if isinstance(entry, dict)],
                    feedback_reports=[entry for entry in case.get("feedback_reports", []) if isinstance(entry, dict)],
                    latest_trajectory_plan=case.get("latest_trajectory_plan"),
                )
                second = self.aggregator.aggregate(
                    candidate_id=str(case["candidate_id"]),
                    target_role=str(case["target_role"]),
                    request_payload=dict(case.get("request_payload", {})),
                    candidate_profile=dict(case.get("candidate_profile", {})),
                    interview_sessions=[entry for entry in case.get("interview_sessions", []) if isinstance(entry, dict)],
                    feedback_reports=[entry for entry in case.get("feedback_reports", []) if isinstance(entry, dict)],
                    latest_trajectory_plan=case.get("latest_trajectory_plan"),
                )
                self.assertEqual(first, second)

                expectations = case.get("expectations", {})
                self.assertEqual(first.get("history_counts"), expectations.get("history_counts"))

                leverage_signals = first.get("leverage_signals")
                self.assertIsInstance(leverage_signals, list)
                assert isinstance(leverage_signals, list)
                self.assertEqual(
                    [entry.get("signal") for entry in leverage_signals],
                    expectations.get("leverage_signal_order"),
                )
                for entry in leverage_signals:
                    self.assertIn(entry.get("strength"), {"low", "medium", "high"})
                    self.assertIsInstance(entry.get("score"), (int, float))
                    self.assertGreaterEqual(float(entry.get("score", 0.0)), 0.0)
                    self.assertLessEqual(float(entry.get("score", 0.0)), 100.0)
                    self.assertTrue(str(entry.get("evidence", "")).strip())

                risk_signals = first.get("risk_signals")
                self.assertIsInstance(risk_signals, list)
                assert isinstance(risk_signals, list)
                self.assertEqual(
                    [entry.get("signal") for entry in risk_signals],
                    expectations.get("risk_signal_order"),
                )
                for entry in risk_signals:
                    self.assertIn(entry.get("severity"), {"low", "medium", "high", "critical"})
                    self.assertIsInstance(entry.get("score"), (int, float))
                    self.assertGreaterEqual(float(entry.get("score", 0.0)), 0.0)
                    self.assertLessEqual(float(entry.get("score", 0.0)), 100.0)
                    self.assertTrue(str(entry.get("evidence", "")).strip())

                evidence_links = first.get("evidence_links")
                self.assertIsInstance(evidence_links, list)
                assert isinstance(evidence_links, list)
                self.assertEqual(
                    [entry.get("source_type") for entry in evidence_links],
                    expectations.get("evidence_source_order"),
                )
                for entry in evidence_links:
                    self.assertTrue(str(entry.get("source_type", "")).strip())
                    self.assertTrue(str(entry.get("source_id", "")).strip())
                    self.assertTrue(str(entry.get("detail", "")).strip())

                adjustments = first.get("compensation_adjustments")
                self.assertIsInstance(adjustments, dict)
                assert isinstance(adjustments, dict)
                expected_adjustments = expectations.get("compensation_adjustments", {})
                for key, expected_value in expected_adjustments.items():
                    self.assertAlmostEqual(float(adjustments.get(key, -999.0)), float(expected_value), places=2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
