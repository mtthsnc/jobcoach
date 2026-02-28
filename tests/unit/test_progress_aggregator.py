from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
AGGREGATOR_PATH = ROOT / "services" / "progress-tracking" / "aggregator.py"


def _load_aggregator_module():
    spec = importlib.util.spec_from_file_location("progress_tracking_aggregator", AGGREGATOR_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load progress aggregator module: {AGGREGATOR_PATH}")

    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class ProgressAggregatorTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        module = _load_aggregator_module()
        cls.aggregator = module.LongitudinalProgressAggregator()

    def test_aggregate_is_deterministic_for_fixed_history(self) -> None:
        interview_sessions = [
            {
                "session_id": "sess_001",
                "created_at": "2026-02-01T10:00:00+00:00",
                "scores": {
                    "skill.execution": 45,
                    "skill.communication": 55,
                },
                "overall_score": 50,
            },
            {
                "session_id": "sess_002",
                "created_at": "2026-02-10T10:00:00+00:00",
                "scores": {
                    "skill.execution": 66,
                    "skill.communication": 63,
                    "skill.system_design": 54,
                },
                "overall_score": 61,
            },
        ]
        feedback_reports = [
            {
                "feedback_report_id": "fb_001",
                "generated_at": "2026-02-05T10:00:00+00:00",
                "competency_scores": {
                    "skill.execution": 58,
                    "skill.communication": 60,
                },
                "overall_score": 59,
            },
            {
                "feedback_report_id": "fb_002",
                "generated_at": "2026-02-12T10:00:00+00:00",
                "competency_scores": {
                    "skill.execution": 72,
                    "skill.communication": 68,
                    "skill.system_design": 62,
                },
                "overall_score": 67.33,
            },
        ]

        first = self.aggregator.aggregate(interview_sessions=interview_sessions, feedback_reports=feedback_reports)
        second = self.aggregator.aggregate(interview_sessions=interview_sessions, feedback_reports=feedback_reports)
        self.assertEqual(first, second)

        self.assertEqual(first["history_counts"]["interview_sessions"], 2)
        self.assertEqual(first["history_counts"]["feedback_reports"], 2)
        self.assertEqual(first["history_counts"]["snapshots"], 4)
        self.assertEqual(first["baseline"]["source_id"], "sess_001")
        self.assertEqual(first["current"]["source_id"], "fb_002")
        self.assertEqual(first["delta"]["overall_score"], 17.33)

        competency_trends = first["competency_trends"]
        self.assertEqual(
            [entry["competency"] for entry in competency_trends],
            ["skill.execution", "skill.communication", "skill.system_design"],
        )
        self.assertEqual(competency_trends[0]["delta_score"], 27.0)
        self.assertEqual(competency_trends[1]["delta_score"], 13.0)
        self.assertEqual(competency_trends[2]["delta_score"], 8.0)
        self.assertEqual(competency_trends[2]["observation_count"], 2)

        self.assertEqual(first["top_improving_competencies"], ["skill.execution", "skill.communication", "skill.system_design"])
        self.assertEqual(first["top_risk_competencies"], ["skill.system_design", "skill.communication", "skill.execution"])

    def test_aggregate_falls_back_to_question_scores_when_session_scores_missing(self) -> None:
        summary = self.aggregator.aggregate(
            interview_sessions=[
                {
                    "session_id": "sess_fallback_001",
                    "created_at": "2026-02-01T09:00:00+00:00",
                    "scores": {},
                    "questions": [
                        {"competency": "execution", "score": 40},
                        {"competency": "skill.execution", "score": 60},
                        {"competency": "communication", "score": 80},
                    ],
                }
            ],
            feedback_reports=[],
        )

        self.assertEqual(summary["history_counts"]["snapshots"], 1)
        self.assertEqual(summary["baseline"]["source_id"], "sess_fallback_001")
        self.assertEqual(summary["baseline"]["overall_score"], 65.0)
        self.assertEqual(summary["current"]["overall_score"], 65.0)
        self.assertEqual(summary["delta"]["overall_score"], 0.0)
        self.assertEqual(
            summary["competency_trends"],
            [
                {
                    "competency": "skill.communication",
                    "baseline_score": 80.0,
                    "current_score": 80.0,
                    "delta_score": 0.0,
                    "observation_count": 1,
                },
                {
                    "competency": "skill.execution",
                    "baseline_score": 50.0,
                    "current_score": 50.0,
                    "delta_score": 0.0,
                    "observation_count": 1,
                },
            ],
        )
        self.assertEqual(summary["top_risk_competencies"], ["skill.execution", "skill.communication"])

    def test_aggregate_empty_history_returns_null_baseline_current_delta(self) -> None:
        summary = self.aggregator.aggregate(interview_sessions=[], feedback_reports=[])
        self.assertEqual(
            summary,
            {
                "history_counts": {"interview_sessions": 0, "feedback_reports": 0, "snapshots": 0},
                "baseline": {},
                "current": {},
                "delta": {},
                "competency_trends": [],
                "top_improving_competencies": [],
                "top_risk_competencies": [],
            },
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
