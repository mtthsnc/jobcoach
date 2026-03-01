from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
GENERATOR_PATH = ROOT / "services" / "negotiation-planning" / "generator.py"
FIXTURE_DIR = ROOT / "tests" / "unit" / "fixtures" / "negotiation_strategy"


def _load_generator_module():
    spec = importlib.util.spec_from_file_location("negotiation_strategy_generator", GENERATOR_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load negotiation strategy generator module: {GENERATOR_PATH}")

    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _load_fixture(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


class NegotiationStrategyGeneratorTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        module = _load_generator_module()
        cls.generator = module.DeterministicNegotiationStrategyGenerator()

    def test_fixture_cases_are_deterministic_with_bounded_strategy_outputs(self) -> None:
        fixture_paths = sorted(FIXTURE_DIR.glob("benchmark_*.json"))
        self.assertGreater(len(fixture_paths), 0, "expected negotiation strategy fixtures")

        for fixture_path in fixture_paths:
            case = _load_fixture(fixture_path)
            with self.subTest(case=case.get("case_id", fixture_path.name)):
                first = self.generator.generate(
                    target_role=str(case.get("target_role", "")),
                    compensation_targets=dict(case.get("compensation_targets", {})),
                    leverage_signals=[entry for entry in case.get("leverage_signals", []) if isinstance(entry, dict)],
                    risk_signals=[entry for entry in case.get("risk_signals", []) if isinstance(entry, dict)],
                    evidence_links=[entry for entry in case.get("evidence_links", []) if isinstance(entry, dict)],
                )
                second = self.generator.generate(
                    target_role=str(case.get("target_role", "")),
                    compensation_targets=dict(case.get("compensation_targets", {})),
                    leverage_signals=[entry for entry in case.get("leverage_signals", []) if isinstance(entry, dict)],
                    risk_signals=[entry for entry in case.get("risk_signals", []) if isinstance(entry, dict)],
                    evidence_links=[entry for entry in case.get("evidence_links", []) if isinstance(entry, dict)],
                )
                self.assertEqual(first, second)

                expectations = case.get("expectations", {})
                anchor_band = first.get("anchor_band")
                self.assertIsInstance(anchor_band, dict)
                assert isinstance(anchor_band, dict)
                expected_anchor = expectations.get("anchor_band", {})
                self.assertEqual(anchor_band.get("floor_base_salary"), expected_anchor.get("floor_base_salary"))
                self.assertEqual(anchor_band.get("target_base_salary"), expected_anchor.get("target_base_salary"))
                self.assertEqual(anchor_band.get("ceiling_base_salary"), expected_anchor.get("ceiling_base_salary"))
                self.assertLessEqual(anchor_band.get("floor_base_salary", 0), anchor_band.get("target_base_salary", 0))
                self.assertLessEqual(anchor_band.get("target_base_salary", 0), anchor_band.get("ceiling_base_salary", 0))
                self.assertTrue(str(anchor_band.get("rationale", "")).strip())

                concession_ladder = first.get("concession_ladder")
                self.assertIsInstance(concession_ladder, list)
                assert isinstance(concession_ladder, list)
                self.assertEqual(len(concession_ladder), int(expectations.get("concession_steps", 0)))
                self.assertEqual([item.get("step") for item in concession_ladder], list(range(1, len(concession_ladder) + 1)))
                asks = [int(item.get("ask_base_salary", 0)) for item in concession_ladder]
                self.assertEqual(asks, sorted(asks, reverse=True))
                for item in concession_ladder:
                    self.assertTrue(str(item.get("trigger", "")).strip())
                    self.assertTrue(str(item.get("concession", "")).strip())
                    self.assertTrue(str(item.get("exchange_for", "")).strip())
                    self.assertTrue(str(item.get("evidence", "")).strip())

                objection_playbook = first.get("objection_playbook")
                self.assertIsInstance(objection_playbook, list)
                assert isinstance(objection_playbook, list)
                self.assertEqual(
                    [item.get("risk_signal") for item in objection_playbook],
                    expectations.get("objection_signal_order"),
                )
                for item in objection_playbook:
                    self.assertTrue(str(item.get("objection", "")).strip())
                    self.assertTrue(str(item.get("response", "")).strip())
                    self.assertTrue(str(item.get("evidence", "")).strip())
                    self.assertTrue(str(item.get("fallback_trade", "")).strip())

                self.assertTrue(str(first.get("strategy_summary", "")).strip())
                talking_points = first.get("talking_points")
                self.assertIsInstance(talking_points, list)
                assert isinstance(talking_points, list)
                self.assertGreaterEqual(len(talking_points), 3)
                for point in talking_points:
                    self.assertTrue(str(point).strip())


if __name__ == "__main__":
    unittest.main(verbosity=2)
