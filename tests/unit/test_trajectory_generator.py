from __future__ import annotations

import importlib.util
import sys
import unittest
from datetime import date
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
GENERATOR_PATH = ROOT / "services" / "trajectory-planning" / "generator.py"


def _load_generator_module():
    spec = importlib.util.spec_from_file_location("trajectory_planning_generator", GENERATOR_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load trajectory generator module: {GENERATOR_PATH}")

    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class TrajectoryGeneratorTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        module = _load_generator_module()
        cls.planner = module.DeterministicTrajectoryPlanner()

    def test_generate_is_deterministic_with_date_ordered_milestones_and_evidence_actions(self) -> None:
        candidate_profile = {
            "candidate_id": "cand_fixture_001",
            "skills": {
                "python": 0.92,
                "system_design": 0.61,
                "communication": 0.55,
            },
        }
        progress_summary = {
            "history_counts": {"interview_sessions": 2, "feedback_reports": 2, "snapshots": 4},
            "baseline": {"overall_score": 61.0},
            "current": {"overall_score": 66.0},
            "delta": {"overall_score": 5.0},
            "competency_trends": [
                {
                    "competency": "skill.communication",
                    "baseline_score": 58.0,
                    "current_score": 52.0,
                    "delta_score": -6.0,
                    "observation_count": 3,
                },
                {
                    "competency": "skill.system_design",
                    "baseline_score": 61.0,
                    "current_score": 58.0,
                    "delta_score": -3.0,
                    "observation_count": 3,
                },
                {
                    "competency": "skill.sql",
                    "baseline_score": 62.0,
                    "current_score": 64.0,
                    "delta_score": 2.0,
                    "observation_count": 2,
                },
                {
                    "competency": "skill.python",
                    "baseline_score": 85.0,
                    "current_score": 86.0,
                    "delta_score": 1.0,
                    "observation_count": 2,
                },
            ],
            "top_improving_competencies": ["skill.sql", "skill.python"],
            "top_risk_competencies": ["skill.communication", "skill.system_design", "skill.problem_solving"],
        }

        first = self.planner.generate(
            candidate_profile=candidate_profile,
            target_role="Principal Backend Engineer",
            progress_summary=progress_summary,
            reference_date=date(2026, 2, 28),
        )
        second = self.planner.generate(
            candidate_profile=candidate_profile,
            target_role="Principal Backend Engineer",
            progress_summary=progress_summary,
            reference_date=date(2026, 2, 28),
        )
        self.assertEqual(first, second)

        milestones = first.get("milestones")
        self.assertIsInstance(milestones, list)
        self.assertGreaterEqual(len(milestones), 3)
        assert isinstance(milestones, list)
        dates = [item["target_date"] for item in milestones]
        self.assertEqual(dates, sorted(dates))
        self.assertIn("current=", milestones[0]["metric"])
        self.assertIn("target=", milestones[0]["metric"])
        self.assertIn("delta=", milestones[0]["metric"])

        weekly_plan = first.get("weekly_plan")
        self.assertIsInstance(weekly_plan, list)
        assert isinstance(weekly_plan, list)
        self.assertGreaterEqual(len(weekly_plan), 4)
        self.assertLessEqual(len(weekly_plan), 8)
        self.assertEqual([entry.get("week") for entry in weekly_plan], list(range(1, len(weekly_plan) + 1)))

        first_week_actions = " ".join(weekly_plan[0].get("actions", [])).lower()
        self.assertIn("current=", first_week_actions)
        self.assertIn("target=", first_week_actions)
        self.assertIn("delta=", first_week_actions)
        self.assertIn("communication", first_week_actions)

    def test_generate_handles_empty_progress_summary_with_bounded_plan(self) -> None:
        generated = self.planner.generate(
            candidate_profile={"candidate_id": "cand_empty_001", "skills": {}},
            target_role="Backend Engineer",
            progress_summary={
                "history_counts": {"interview_sessions": 0, "feedback_reports": 0, "snapshots": 0},
                "baseline": {},
                "current": {},
                "delta": {},
                "competency_trends": [],
                "top_improving_competencies": [],
                "top_risk_competencies": [],
            },
            reference_date=date(2026, 2, 28),
        )

        self.assertEqual(generated.get("horizon_months"), 3)
        self.assertIsInstance(generated.get("role_readiness_score"), (int, float))

        milestones = generated.get("milestones")
        self.assertIsInstance(milestones, list)
        assert isinstance(milestones, list)
        self.assertEqual([item["target_date"] for item in milestones], sorted(item["target_date"] for item in milestones))

        weekly_plan = generated.get("weekly_plan")
        self.assertIsInstance(weekly_plan, list)
        assert isinstance(weekly_plan, list)
        self.assertGreaterEqual(len(weekly_plan), 4)
        for entry in weekly_plan:
            self.assertIsInstance(entry.get("week"), int)
            self.assertIsInstance(entry.get("actions"), list)
            for action in entry.get("actions", []):
                self.assertTrue(str(action).strip())


if __name__ == "__main__":
    unittest.main(verbosity=2)

