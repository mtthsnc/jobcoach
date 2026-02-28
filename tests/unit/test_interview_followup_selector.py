from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
FOLLOWUP_SELECTOR_PATH = ROOT / "services" / "interview-engine" / "followup.py"


def _load_module(module_name: str, module_path: Path):
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load module: {module_path}")

    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _question(
    *,
    question_id: str,
    competency: str,
    difficulty: int,
    response: str,
    score: float,
    ranking_position: int,
) -> dict[str, Any]:
    return {
        "question_id": question_id,
        "text": "placeholder",
        "competency": competency,
        "difficulty": difficulty,
        "response": response,
        "score": score,
        "planner_metadata": {
            "source_competency": competency,
            "ranking_position": ranking_position,
            "deterministic_confidence": 0.8,
        },
    }


class InterviewFollowupSelectorTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.selector_module = _load_module("interview_followup_selector_test", FOLLOWUP_SELECTOR_PATH)

    def test_selector_targets_low_score_remediation_for_recent_turn(self) -> None:
        selector = self.selector_module.AdaptiveFollowupSelector()
        questions = [
            _question(
                question_id="q_1",
                competency="skill.python",
                difficulty=4,
                response="I shipped API migrations across teams.",
                score=56.0,
                ranking_position=1,
            ),
            _question(
                question_id="q_2",
                competency="skill.sql",
                difficulty=3,
                response="I optimized queries and reduced latency by 25%.",
                score=81.0,
                ranking_position=2,
            ),
        ]
        decision = selector.select_followup(
            questions=questions,
            scores={"skill.python": 56.0, "skill.sql": 81.0},
            last_question=questions[0],
            last_score=56.0,
        )

        self.assertEqual(decision["competency"], "skill.python")
        self.assertEqual(decision["reason"], "low_score_remediation")
        self.assertGreaterEqual(int(decision["difficulty"]), 1)
        self.assertLessEqual(int(decision["difficulty"]), 5)

    def test_selector_avoids_repeating_recent_competency_when_score_is_strong(self) -> None:
        selector = self.selector_module.AdaptiveFollowupSelector()
        questions = [
            _question(
                question_id="q_1",
                competency="skill.python",
                difficulty=2,
                response="I designed and delivered API migrations with strong uptime outcomes.",
                score=88.0,
                ranking_position=1,
            ),
            _question(
                question_id="q_2",
                competency="skill.sql",
                difficulty=3,
                response="I reduced slow-query p95 by 30%.",
                score=58.0,
                ranking_position=2,
            ),
            _question(
                question_id="q_3",
                competency="skill.communication",
                difficulty=3,
                response="I aligned stakeholders across platform dependencies.",
                score=84.0,
                ranking_position=3,
            ),
        ]
        decision = selector.select_followup(
            questions=questions,
            scores={"skill.python": 88.0, "skill.sql": 58.0, "skill.communication": 84.0},
            last_question=questions[0],
            last_score=88.0,
        )

        self.assertNotEqual(decision["competency"], "skill.python")
        self.assertEqual(decision["competency"], "skill.sql")
        self.assertEqual(decision["reason"], "coverage_gap")

    def test_selector_is_deterministic_for_fixed_inputs(self) -> None:
        selector = self.selector_module.AdaptiveFollowupSelector()
        questions = [
            _question(
                question_id="q_1",
                competency="skill.api_design",
                difficulty=4,
                response="I shipped API policy changes with measurable reliability impact.",
                score=78.0,
                ranking_position=1,
            ),
            _question(
                question_id="q_2",
                competency="skill.system_design",
                difficulty=5,
                response="I designed service boundaries and improved deployment safety.",
                score=71.0,
                ranking_position=2,
            ),
        ]

        first = selector.select_followup(
            questions=questions,
            scores={"skill.api_design": 78.0, "skill.system_design": 71.0},
            last_question=questions[1],
            last_score=71.0,
        )
        second = selector.select_followup(
            questions=questions,
            scores={"skill.api_design": 78.0, "skill.system_design": 71.0},
            last_question=questions[1],
            last_score=71.0,
        )

        self.assertEqual(first, second)
        self.assertLessEqual(int(first["difficulty"]), 5)


if __name__ == "__main__":
    unittest.main(verbosity=2)
