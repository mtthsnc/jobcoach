from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PLANNER_PATH = ROOT / "services" / "negotiation-planning" / "followup.py"
FIXTURE_DIR = ROOT / "tests" / "unit" / "fixtures" / "negotiation_followup"


def _load_planner_module():
    spec = importlib.util.spec_from_file_location("negotiation_followup_planner", PLANNER_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load negotiation follow-up planner module: {PLANNER_PATH}")

    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _load_fixture(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


class NegotiationFollowupPlannerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        module = _load_planner_module()
        cls.planner = module.DeterministicNegotiationFollowupPlanner()

    def test_fixture_cases_are_deterministic_with_bounded_followup_outputs(self) -> None:
        fixture_paths = sorted(FIXTURE_DIR.glob("benchmark_*.json"))
        self.assertGreater(len(fixture_paths), 0, "expected negotiation follow-up fixtures")

        for fixture_path in fixture_paths:
            case = _load_fixture(fixture_path)
            with self.subTest(case=case.get("case_id", fixture_path.name)):
                first = self.planner.generate(
                    target_role=str(case.get("target_role", "")),
                    strategy_summary=str(case.get("strategy_summary", "")),
                    anchor_band=dict(case.get("anchor_band", {})),
                    concession_ladder=[entry for entry in case.get("concession_ladder", []) if isinstance(entry, dict)],
                    leverage_signals=[entry for entry in case.get("leverage_signals", []) if isinstance(entry, dict)],
                    risk_signals=[entry for entry in case.get("risk_signals", []) if isinstance(entry, dict)],
                    evidence_links=[entry for entry in case.get("evidence_links", []) if isinstance(entry, dict)],
                )
                second = self.planner.generate(
                    target_role=str(case.get("target_role", "")),
                    strategy_summary=str(case.get("strategy_summary", "")),
                    anchor_band=dict(case.get("anchor_band", {})),
                    concession_ladder=[entry for entry in case.get("concession_ladder", []) if isinstance(entry, dict)],
                    leverage_signals=[entry for entry in case.get("leverage_signals", []) if isinstance(entry, dict)],
                    risk_signals=[entry for entry in case.get("risk_signals", []) if isinstance(entry, dict)],
                    evidence_links=[entry for entry in case.get("evidence_links", []) if isinstance(entry, dict)],
                )
                self.assertEqual(first, second)

                expectations = case.get("expectations", {})
                follow_up_plan = first.get("follow_up_plan")
                self.assertIsInstance(follow_up_plan, dict)
                assert isinstance(follow_up_plan, dict)

                thank_you_note = follow_up_plan.get("thank_you_note")
                self.assertIsInstance(thank_you_note, dict)
                assert isinstance(thank_you_note, dict)
                self.assertEqual(int(thank_you_note.get("send_by_day_offset", -1)), 0)
                self.assertTrue(str(thank_you_note.get("subject", "")).strip())
                self.assertTrue(str(thank_you_note.get("body", "")).strip())
                self.assertIsInstance(thank_you_note.get("key_points"), list)
                self.assertGreaterEqual(len(thank_you_note.get("key_points", [])), 1)

                recruiter_cadence = follow_up_plan.get("recruiter_cadence")
                self.assertIsInstance(recruiter_cadence, list)
                assert isinstance(recruiter_cadence, list)
                self.assertEqual(
                    [int(item.get("day_offset", -1)) for item in recruiter_cadence],
                    expectations.get("cadence_offsets"),
                )
                for item in recruiter_cadence:
                    self.assertIn(item.get("channel"), {"email", "phone", "linkedin"})
                    self.assertTrue(str(item.get("objective", "")).strip())
                    self.assertTrue(str(item.get("message", "")).strip())

                branches = follow_up_plan.get("outcome_branches")
                self.assertIsInstance(branches, list)
                assert isinstance(branches, list)
                self.assertEqual(
                    [str(item.get("outcome", "")) for item in branches],
                    expectations.get("branch_order"),
                )
                for branch in branches:
                    self.assertIsInstance(branch.get("actions"), list)
                    for action in branch.get("actions", []):
                        self.assertIsInstance(action.get("day_offset"), int)
                        self.assertTrue(str(action.get("action", "")).strip())

                follow_up_actions = first.get("follow_up_actions")
                self.assertIsInstance(follow_up_actions, list)
                assert isinstance(follow_up_actions, list)
                self.assertGreaterEqual(len(follow_up_actions), 3)
                offsets = [int(item.get("day_offset", -1)) for item in follow_up_actions]
                self.assertEqual(offsets, sorted(offsets))
                self.assertLessEqual(max(offsets), int(expectations.get("actions_max_day_offset", 30)))
                for item in follow_up_actions:
                    self.assertTrue(str(item.get("action", "")).strip())


if __name__ == "__main__":
    unittest.main(verbosity=2)
