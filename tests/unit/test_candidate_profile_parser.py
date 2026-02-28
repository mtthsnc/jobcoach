from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PARSER_PATH = ROOT / "services" / "candidate-profile" / "parser.py"
VALIDATOR_PATH = ROOT / "services" / "quality-eval" / "schema_validation" / "validator.py"
FIXTURE_DIR = ROOT / "tests" / "unit" / "fixtures" / "candidate_parsing"


def _load_module(module_name: str, module_path: Path):
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load module: {module_path}")

    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class CandidateProfileParserTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.parser_module = _load_module("candidate_profile_parser_test", PARSER_PATH)
        cls.validator_module = _load_module("schema_validation_validator_for_candidate_parser", VALIDATOR_PATH)
        cls.validator = cls.validator_module.CoreSchemaValidator.from_file()

    def test_fixture_cases_parse_to_schema_valid_candidate_profiles(self) -> None:
        fixtures = sorted(FIXTURE_DIR.glob("*.json"))
        self.assertGreater(len(fixtures), 0)
        parser = self.parser_module.CandidateProfileParser()

        for fixture_path in fixtures:
            case = json.loads(fixture_path.read_text(encoding="utf-8"))
            parsed = parser.parse(**case["input"])
            expectations = case.get("expectations", {})

            with self.subTest(case=case.get("case_id", fixture_path.name)):
                validation = self.validator.validate("CandidateProfile", parsed)
                self.assertTrue(validation.is_valid, f"Validation issues: {validation.issues}")

                expected_candidate_id = expectations.get("candidate_id")
                if expected_candidate_id is not None:
                    self.assertEqual(parsed["candidate_id"], expected_candidate_id)

                expected_summary = expectations.get("summary")
                if expected_summary is not None:
                    self.assertEqual(parsed["summary"], expected_summary)

                experience_min_items = int(expectations.get("experience_min_items", 0))
                self.assertGreaterEqual(len(parsed["experience"]), experience_min_items)

                for required_skill in expectations.get("required_skill_keys", []):
                    self.assertIn(required_skill, parsed["skills"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
