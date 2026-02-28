from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
VALIDATOR_PATH = ROOT / "services" / "quality-eval" / "schema_validation" / "validator.py"
FIXTURES_ROOT = ROOT / "tests" / "contracts" / "fixtures" / "schema_validation"


def _load_validator_module():
    spec = importlib.util.spec_from_file_location("schema_validation_validator", VALIDATOR_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load schema validator module: {VALIDATOR_PATH}")

    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _load_fixture(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


class SchemaValidationContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        module = _load_validator_module()
        cls.validator = module.CoreSchemaValidator.from_file()

    def test_valid_fixtures_pass_validation(self) -> None:
        valid_cases = {
            "JobSpec": "job_spec.json",
            "CandidateProfile": "candidate_profile.json",
            "InterviewSession": "interview_session.json",
            "FeedbackReport": "feedback_report.json",
            "NegotiationPlan": "negotiation_plan.json",
            "TrajectoryPlan": "trajectory_plan.json",
        }

        for entity_name, fixture_name in valid_cases.items():
            with self.subTest(entity_name=entity_name):
                payload = _load_fixture(FIXTURES_ROOT / "valid" / fixture_name)
                result = self.validator.validate(entity_name, payload)
                self.assertTrue(result.is_valid, f"{entity_name} issues: {result.issues}")

    def test_invalid_fixtures_fail_validation(self) -> None:
        invalid_cases = {
            "JobSpec": {
                "fixture": "job_spec_missing_role_title.json",
                "path": "$",
                "message": "missing required field 'role_title'",
            },
            "CandidateProfile": {
                "fixture": "candidate_profile_skill_out_of_range.json",
                "path": "$.skills.python",
                "message": "value must be <= 1",
            },
            "InterviewSession": {
                "fixture": "interview_session_bad_difficulty.json",
                "path": "$.questions[0].difficulty",
                "message": "value must be <= 5",
            },
            "FeedbackReport": {
                "fixture": "feedback_report_bad_severity.json",
                "path": "$.top_gaps[0].severity",
                "message": "enum",
            },
            "NegotiationPlan": {
                "fixture": "negotiation_plan_negative_day_offset.json",
                "path": "$.follow_up_actions[0].day_offset",
                "message": "value must be >= 0",
            },
            "TrajectoryPlan": {
                "fixture": "trajectory_plan_bad_target_date.json",
                "path": "$.milestones[0].target_date",
                "message": "ISO-8601 date",
            },
        }

        for entity_name, case in invalid_cases.items():
            with self.subTest(entity_name=entity_name):
                payload = _load_fixture(FIXTURES_ROOT / "invalid" / case["fixture"])
                result = self.validator.validate(entity_name, payload)
                self.assertFalse(result.is_valid, "Expected fixture to fail validation")
                self.assertTrue(
                    any(issue.path == case["path"] and case["message"] in issue.message for issue in result.issues),
                    f"Missing expected issue for {entity_name}: {result.issues}",
                )

    def test_unknown_entity_raises_value_error(self) -> None:
        with self.assertRaises(ValueError):
            self.validator.validate("NotARealEntity", {})


if __name__ == "__main__":
    unittest.main(verbosity=2)
