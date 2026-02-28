from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PLANNER_PATH = ROOT / "services" / "interview-engine" / "planner.py"


def _load_module(module_name: str, module_path: Path):
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load module: {module_path}")

    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class InterviewQuestionPlannerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.planner_module = _load_module("interview_question_planner_test", PLANNER_PATH)

    def test_planner_emits_ranked_questions_with_metadata(self) -> None:
        planner = self.planner_module.DeterministicQuestionPlanner()
        questions = planner.plan_opening_questions(
            session_id="sess_test_001",
            job_spec={
                "competency_weights": {
                    "skill.python": 0.95,
                    "skill.leadership": 0.7,
                    "skill.communication": 0.4,
                }
            },
            candidate_profile={
                "skills": {
                    "python": 0.9,
                    "leadership": 0.2,
                    "communication": 0.85,
                }
            },
        )

        self.assertEqual(len(questions), 3)
        self.assertEqual([question["competency"] for question in questions], ["skill.leadership", "skill.python", "skill.communication"])

        for idx, question in enumerate(questions, start=1):
            metadata = question.get("planner_metadata")
            self.assertIsInstance(metadata, dict)
            self.assertEqual(metadata.get("source_competency"), question["competency"])
            self.assertEqual(metadata.get("ranking_position"), idx)
            confidence = metadata.get("deterministic_confidence")
            self.assertIsInstance(confidence, float)
            self.assertGreaterEqual(float(confidence), 0.5)
            self.assertLessEqual(float(confidence), 0.99)

    def test_planner_output_is_stable_for_fixed_inputs(self) -> None:
        planner = self.planner_module.DeterministicQuestionPlanner()
        job_spec = {
            "competency_weights": {
                "skill.api_design": 0.8,
                "skill.system_design": 0.75,
                "skill.communication": 0.5,
            }
        }
        candidate_profile = {
            "skills": {
                "api_design": 0.4,
                "system_design": 0.3,
                "communication": 0.85,
            }
        }

        first = planner.plan_opening_questions(
            session_id="sess_alpha",
            job_spec=job_spec,
            candidate_profile=candidate_profile,
        )
        second = planner.plan_opening_questions(
            session_id="sess_beta",
            job_spec=job_spec,
            candidate_profile=candidate_profile,
        )

        def signature(values: list[dict]) -> list[tuple]:
            return [
                (
                    value["competency"],
                    value["text"],
                    value["difficulty"],
                    value["planner_metadata"]["ranking_position"],
                    value["planner_metadata"]["deterministic_confidence"],
                )
                for value in values
            ]

        self.assertEqual(signature(first), signature(second))
        self.assertEqual(first[0]["question_id"], "q_alpha_1")
        self.assertEqual(second[0]["question_id"], "q_beta_1")

    def test_planner_falls_back_to_execution_when_competencies_missing(self) -> None:
        planner = self.planner_module.DeterministicQuestionPlanner()
        questions = planner.plan_opening_questions(
            session_id="sess_fallback",
            job_spec={},
            candidate_profile={},
        )

        self.assertEqual(len(questions), 1)
        self.assertEqual(questions[0]["competency"], "execution")
        self.assertEqual(questions[0]["planner_metadata"]["ranking_position"], 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
