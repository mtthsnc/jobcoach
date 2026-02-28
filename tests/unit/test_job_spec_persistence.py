from __future__ import annotations

import importlib.util
import io
import json
import re
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

API_GATEWAY_DIR = ROOT / "apps" / "api-gateway"
if str(API_GATEWAY_DIR) not in sys.path:
    sys.path.insert(0, str(API_GATEWAY_DIR))

from api_gateway.app import create_app

MIGRATIONS_DIR = ROOT / "infra" / "migrations"
VALIDATOR_PATH = ROOT / "services" / "quality-eval" / "schema_validation" / "validator.py"

UP_MARKER = re.compile(r"^\s*--\s*\+goose\s+Up\s*$")
DOWN_MARKER = re.compile(r"^\s*--\s*\+goose\s+Down\s*$")


def _load_validator_module():
    spec = importlib.util.spec_from_file_location("schema_validation_validator", VALIDATOR_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load schema validator module: {VALIDATOR_PATH}")

    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _parse_up_sql(path: Path) -> str:
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    up_idx = None
    down_idx = None

    for idx, line in enumerate(lines):
        if up_idx is None and UP_MARKER.match(line):
            up_idx = idx
            continue
        if up_idx is not None and DOWN_MARKER.match(line):
            down_idx = idx
            break

    if up_idx is None:
        raise RuntimeError(f"{path.name}: missing '-- +goose Up' marker")
    if down_idx is None:
        raise RuntimeError(f"{path.name}: missing '-- +goose Down' marker")

    sql = "".join(lines[up_idx + 1 : down_idx]).strip()
    if not sql:
        raise RuntimeError(f"{path.name}: Up section is empty")
    return sql + "\n"


def _bootstrap_sqlite_schema(db_path: Path) -> None:
    migration_files = sorted(MIGRATIONS_DIR.glob("*.sql"))
    if not migration_files:
        raise RuntimeError(f"No migrations found in {MIGRATIONS_DIR}")

    with closing(sqlite3.connect(db_path)) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        for migration in migration_files:
            conn.executescript(_parse_up_sql(migration))
        conn.commit()


def _request(
    app,
    *,
    method: str,
    path: str,
    body: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> tuple[int, dict[str, str], dict[str, Any]]:
    body_bytes = b""
    if body is not None:
        body_bytes = json.dumps(body).encode("utf-8")

    path_info, _, query_string = path.partition("?")
    environ: dict[str, Any] = {
        "REQUEST_METHOD": method,
        "PATH_INFO": path_info,
        "QUERY_STRING": query_string,
        "wsgi.input": io.BytesIO(body_bytes),
        "CONTENT_LENGTH": str(len(body_bytes)),
        "CONTENT_TYPE": "application/json",
    }

    if headers:
        for key, value in headers.items():
            normalized = key.upper().replace("-", "_")
            environ[f"HTTP_{normalized}"] = value

    captured: dict[str, Any] = {"status": "500 Internal Server Error", "headers": []}

    def start_response(status: str, response_headers: list[tuple[str, str]]) -> None:
        captured["status"] = status
        captured["headers"] = response_headers

    chunks = app(environ, start_response)
    raw = b"".join(chunks)

    status_code = int(str(captured["status"]).split(" ", 1)[0])
    response_headers = {name: value for name, value in captured["headers"]}
    payload = json.loads(raw.decode("utf-8")) if raw else {}
    return status_code, response_headers, payload


class JobSpecPersistenceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        validator_module = _load_validator_module()
        cls.validator = validator_module.CoreSchemaValidator.from_file()

    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory(prefix="job-spec-persist-")
        self.db_path = Path(self._tmpdir.name) / "jobcoach.sqlite3"
        _bootstrap_sqlite_schema(self.db_path)
        self.app = create_app(db_path=self.db_path)

    def tearDown(self) -> None:
        self._tmpdir.cleanup()

    def _create_job_spec(self) -> tuple[str, str]:
        status, _, create_body = _request(
            self.app,
            method="POST",
            path="/v1/job-ingestions",
            body={
                "source_type": "text",
                "source_value": (
                    "Staff Backend Engineer\n"
                    "Responsibilities:\n"
                    "- Build Python services for ingestion workflows.\n"
                    "- Improve API reliability and SQL-backed persistence.\n"
                    "Requirements:\n"
                    "- Strong Python and SQL fundamentals.\n"
                    "Preferred Qualifications:\n"
                    "- Event driven systems and pub sub experience."
                ),
            },
            headers={"Idempotency-Key": "persist-job-spec-001"},
        )

        self.assertEqual(status, 202, create_body)
        ingestion_id = create_body["data"]["ingestion_id"]
        self.assertTrue(ingestion_id)

        with closing(sqlite3.connect(self.db_path)) as conn:
            ingestion_row = conn.execute(
                "SELECT result_job_spec_id FROM job_ingestions WHERE ingestion_id = ?",
                (ingestion_id,),
            ).fetchone()

        self.assertIsNotNone(ingestion_row)
        assert ingestion_row is not None
        job_spec_id = ingestion_row[0]
        self.assertIsInstance(job_spec_id, str)
        self.assertTrue(job_spec_id)
        return ingestion_id, job_spec_id

    def _create_candidate_profile(self) -> tuple[str, str]:
        create_status, _, create_body = _request(
            self.app,
            method="POST",
            path="/v1/candidate-ingestions",
            body={
                "candidate_id": "cand_interview_unit_001",
                "cv_text": (
                    "Taylor Quinn\n"
                    "Staff Engineer\n"
                    "Acme Corp | Staff Engineer | 2021-01 - Present\n"
                    "Built Python and SQL workflow systems with measurable reliability gains.\n"
                ),
                "target_roles": ["Staff Engineer"],
                "story_notes": ["Improved deployment success rate to 98%."],
            },
            headers={"Idempotency-Key": "candidate-interview-unit-001"},
        )
        self.assertEqual(create_status, 202, create_body)
        ingestion_id = create_body["data"]["ingestion_id"]
        self.assertTrue(ingestion_id)

        get_status, _, get_body = _request(
            self.app,
            method="GET",
            path=f"/v1/candidate-ingestions/{ingestion_id}",
        )
        self.assertEqual(get_status, 200, get_body)
        result = get_body["data"].get("result")
        self.assertIsInstance(result, dict)
        candidate_id = result.get("entity_id") if isinstance(result, dict) else None
        self.assertIsInstance(candidate_id, str)
        self.assertTrue(candidate_id)
        assert isinstance(candidate_id, str)
        return ingestion_id, candidate_id

    def test_job_spec_persisted_and_retrievable(self) -> None:
        _, job_spec_id = self._create_job_spec()

        get_status, _, get_body = _request(
            self.app,
            method="GET",
            path=f"/v1/job-specs/{job_spec_id}",
        )

        self.assertEqual(get_status, 200, get_body)
        self.assertIsNone(get_body["error"])

        job_spec_payload = get_body["data"]
        validation = self.validator.validate("JobSpec", job_spec_payload)
        self.assertTrue(validation.is_valid, f"JobSpec validation failed: {validation.issues}")

        self.assertEqual(job_spec_payload["job_spec_id"], job_spec_id)
        self.assertGreaterEqual(job_spec_payload["extraction_confidence"], 0)
        self.assertLessEqual(job_spec_payload["extraction_confidence"], 1)
        self.assertGreater(len(job_spec_payload["responsibilities"]), 0)

    def test_patch_job_spec_review_success_persists_audit_row(self) -> None:
        _, job_spec_id = self._create_job_spec()

        patch_payload = {
            "expected_version": 1,
            "patch": {
                "role_title": "Principal Backend Engineer",
                "requirements": {
                    "preferred_skills": ["Event-Driven Architecture", "API Design"],
                },
                "competency_weights": {
                    "skill.python": 0.95,
                    "skill.api_design": 0.7,
                },
                "extraction_confidence": 0.93,
            },
            "review_notes": "Calibrated to seniority rubric.",
            "reviewed_by": "reviewer@example.com",
        }

        patch_status, _, patch_body = _request(
            self.app,
            method="PATCH",
            path=f"/v1/job-specs/{job_spec_id}/review",
            body=patch_payload,
        )
        self.assertEqual(patch_status, 200, patch_body)
        self.assertIsNone(patch_body["error"])

        updated = patch_body["data"]
        self.assertEqual(updated["job_spec_id"], job_spec_id)
        self.assertEqual(updated["role_title"], "Principal Backend Engineer")
        self.assertEqual(updated["version"], 2)
        self.assertEqual(updated["requirements"]["preferred_skills"], ["Event-Driven Architecture", "API Design"])
        self.assertAlmostEqual(updated["competency_weights"]["skill.python"], 0.95)
        self.assertAlmostEqual(updated["extraction_confidence"], 0.93)

        validation = self.validator.validate("JobSpec", updated)
        self.assertTrue(validation.is_valid, f"Patched JobSpec validation failed: {validation.issues}")

        with closing(sqlite3.connect(self.db_path)) as conn:
            review_row = conn.execute(
                """
                SELECT expected_version, result_version, patch_json, review_notes, reviewed_by
                FROM job_spec_reviews
                WHERE job_spec_id = ?
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (job_spec_id,),
            ).fetchone()

        self.assertIsNotNone(review_row)
        assert review_row is not None
        self.assertEqual(review_row[0], 1)
        self.assertEqual(review_row[1], 2)
        self.assertEqual(review_row[3], "Calibrated to seniority rubric.")
        self.assertEqual(review_row[4], "reviewer@example.com")
        stored_patch = json.loads(review_row[2])
        self.assertEqual(stored_patch["role_title"], "Principal Backend Engineer")

    def test_patch_job_spec_review_version_conflict_returns_409(self) -> None:
        _, job_spec_id = self._create_job_spec()

        first_patch_status, _, first_patch_body = _request(
            self.app,
            method="PATCH",
            path=f"/v1/job-specs/{job_spec_id}/review",
            body={
                "expected_version": 1,
                "patch": {"role_title": "Senior Backend Engineer"},
            },
        )
        self.assertEqual(first_patch_status, 200, first_patch_body)
        self.assertEqual(first_patch_body["data"]["version"], 2)

        conflict_status, _, conflict_body = _request(
            self.app,
            method="PATCH",
            path=f"/v1/job-specs/{job_spec_id}/review",
            body={
                "expected_version": 1,
                "patch": {"role_title": "Staff Backend Engineer"},
            },
        )
        self.assertEqual(conflict_status, 409, conflict_body)
        self.assertIsNone(conflict_body["data"])
        self.assertEqual(conflict_body["error"]["code"], "version_conflict")
        detail_reasons = [detail.get("reason", "") for detail in conflict_body["error"].get("details", [])]
        self.assertTrue(any("current version is 2" in reason for reason in detail_reasons))

    def test_create_and_get_interview_session_persists_schema_valid_row(self) -> None:
        _, job_spec_id = self._create_job_spec()
        _, candidate_id = self._create_candidate_profile()

        create_status, _, create_body = _request(
            self.app,
            method="POST",
            path="/v1/interview-sessions",
            body={
                "job_spec_id": job_spec_id,
                "candidate_id": candidate_id,
                "mode": "mock_interview",
            },
        )
        self.assertEqual(create_status, 201, create_body)
        session_payload = create_body["data"]
        session_id = session_payload["session_id"]
        self.assertTrue(session_id)
        self.assertEqual(session_payload["job_spec_id"], job_spec_id)
        self.assertEqual(session_payload["candidate_id"], candidate_id)
        self.assertIsInstance(session_payload["questions"], list)
        self.assertGreaterEqual(len(session_payload["questions"]), 1)
        ranking_positions = []
        for question in session_payload["questions"]:
            self.assertIn("planner_metadata", question)
            metadata = question["planner_metadata"]
            self.assertIsInstance(metadata, dict)
            self.assertEqual(metadata.get("source_competency"), question.get("competency"))
            self.assertIsInstance(metadata.get("ranking_position"), int)
            self.assertIsInstance(metadata.get("deterministic_confidence"), float)
            ranking_positions.append(int(metadata["ranking_position"]))
        self.assertEqual(ranking_positions, list(range(1, len(ranking_positions) + 1)))

        validation = self.validator.validate("InterviewSession", session_payload)
        self.assertTrue(validation.is_valid, f"InterviewSession validation failed: {validation.issues}")

        with closing(sqlite3.connect(self.db_path)) as conn:
            row = conn.execute(
                """
                SELECT session_id, job_spec_id, candidate_id, mode, status, version
                FROM interview_sessions
                WHERE session_id = ?
                """,
                (session_id,),
            ).fetchone()
        self.assertIsNotNone(row)
        assert row is not None
        self.assertEqual(row[0], session_id)
        self.assertEqual(row[1], job_spec_id)
        self.assertEqual(row[2], candidate_id)
        self.assertEqual(row[3], "mock_interview")
        self.assertEqual(row[4], "in_progress")
        self.assertEqual(row[5], 1)

        get_status, _, get_body = _request(
            self.app,
            method="GET",
            path=f"/v1/interview-sessions/{session_id}",
        )
        self.assertEqual(get_status, 200, get_body)
        self.assertEqual(get_body["data"]["session_id"], session_id)
        get_validation = self.validator.validate("InterviewSession", get_body["data"])
        self.assertTrue(get_validation.is_valid, f"InterviewSession validation failed: {get_validation.issues}")

    def test_create_interview_session_planner_output_is_stable_for_fixed_inputs(self) -> None:
        _, job_spec_id = self._create_job_spec()
        _, candidate_id = self._create_candidate_profile()

        first_status, _, first_body = _request(
            self.app,
            method="POST",
            path="/v1/interview-sessions",
            body={
                "job_spec_id": job_spec_id,
                "candidate_id": candidate_id,
                "mode": "mock_interview",
            },
        )
        self.assertEqual(first_status, 201, first_body)
        first_questions = first_body["data"]["questions"]

        second_status, _, second_body = _request(
            self.app,
            method="POST",
            path="/v1/interview-sessions",
            body={
                "job_spec_id": job_spec_id,
                "candidate_id": candidate_id,
                "mode": "mock_interview",
            },
        )
        self.assertEqual(second_status, 201, second_body)
        second_questions = second_body["data"]["questions"]

        def signature(questions: list[dict[str, Any]]) -> list[tuple[Any, ...]]:
            return [
                (
                    question.get("competency"),
                    question.get("text"),
                    question.get("difficulty"),
                    question.get("planner_metadata", {}).get("ranking_position"),
                    question.get("planner_metadata", {}).get("deterministic_confidence"),
                )
                for question in questions
            ]

        self.assertEqual(signature(first_questions), signature(second_questions))

    def test_append_interview_response_updates_session_and_enforces_idempotency(self) -> None:
        _, job_spec_id = self._create_job_spec()
        _, candidate_id = self._create_candidate_profile()

        create_status, _, create_body = _request(
            self.app,
            method="POST",
            path="/v1/interview-sessions",
            body={"job_spec_id": job_spec_id, "candidate_id": candidate_id},
        )
        self.assertEqual(create_status, 201, create_body)
        session_id = create_body["data"]["session_id"]

        respond_status, _, respond_body = _request(
            self.app,
            method="POST",
            path=f"/v1/interview-sessions/{session_id}/responses",
            body={"response": "I led a migration that improved uptime to 99.9% and reduced incidents by 30%."},
            headers={"Idempotency-Key": "interview-response-key-001"},
        )
        self.assertEqual(respond_status, 200, respond_body)
        updated_session = respond_body["data"]
        self.assertEqual(updated_session["session_id"], session_id)
        self.assertEqual(updated_session["version"], 2)
        self.assertGreaterEqual(updated_session["overall_score"], 0.0)
        self.assertLessEqual(updated_session["overall_score"], 100.0)
        self.assertTrue(any(str(question.get("response", "")).strip() for question in updated_session["questions"]))

        validation = self.validator.validate("InterviewSession", updated_session)
        self.assertTrue(validation.is_valid, f"InterviewSession validation failed: {validation.issues}")

        replay_status, _, replay_body = _request(
            self.app,
            method="POST",
            path=f"/v1/interview-sessions/{session_id}/responses",
            body={"response": "I led a migration that improved uptime to 99.9% and reduced incidents by 30%."},
            headers={"Idempotency-Key": "interview-response-key-001"},
        )
        self.assertEqual(replay_status, 200, replay_body)
        self.assertEqual(replay_body["data"]["version"], 2)

        conflict_status, _, conflict_body = _request(
            self.app,
            method="POST",
            path=f"/v1/interview-sessions/{session_id}/responses",
            body={"response": "Different response payload for same idempotency key."},
            headers={"Idempotency-Key": "interview-response-key-001"},
        )
        self.assertEqual(conflict_status, 409, conflict_body)
        self.assertEqual(conflict_body["error"]["code"], "idempotency_key_conflict")

        with closing(sqlite3.connect(self.db_path)) as conn:
            response_rows = conn.execute(
                """
                SELECT session_id, idempotency_key, question_id, response_text, score
                FROM interview_session_responses
                WHERE session_id = ?
                """,
                (session_id,),
            ).fetchall()
        self.assertEqual(len(response_rows), 1)
        self.assertEqual(response_rows[0][0], session_id)
        self.assertEqual(response_rows[0][1], "interview-response-key-001")
        self.assertTrue(response_rows[0][2])
        self.assertTrue(response_rows[0][3])
        self.assertGreaterEqual(float(response_rows[0][4]), 0.0)
        self.assertLessEqual(float(response_rows[0][4]), 100.0)

    def test_adaptive_followup_avoids_repeating_recent_competency_on_strong_response(self) -> None:
        _, job_spec_id = self._create_job_spec()
        _, candidate_id = self._create_candidate_profile()

        create_status, _, create_body = _request(
            self.app,
            method="POST",
            path="/v1/interview-sessions",
            body={"job_spec_id": job_spec_id, "candidate_id": candidate_id},
        )
        self.assertEqual(create_status, 201, create_body)
        session_id = create_body["data"]["session_id"]
        opening_questions = create_body["data"]["questions"]
        self.assertGreaterEqual(len(opening_questions), 1)

        latest_session = create_body["data"]
        for idx, question in enumerate(opening_questions, start=1):
            respond_status, _, respond_body = _request(
                self.app,
                method="POST",
                path=f"/v1/interview-sessions/{session_id}/responses",
                body={
                    "question_id": question["question_id"],
                    "response": (
                        "I led a cross-functional migration, improved uptime to 99.9%, "
                        "reduced latency by 35%, and shipped safely under deadline pressure."
                    ),
                },
                headers={"Idempotency-Key": f"adaptive-strong-{idx}"},
            )
            self.assertEqual(respond_status, 200, respond_body)
            latest_session = respond_body["data"]

        followup_question = latest_session["questions"][-1]
        self.assertGreater(len(latest_session["questions"]), len(opening_questions))
        self.assertNotEqual(followup_question["competency"], opening_questions[-1]["competency"])
        self.assertGreaterEqual(int(followup_question["difficulty"]), 1)
        self.assertLessEqual(int(followup_question["difficulty"]), 5)

        metadata = followup_question.get("planner_metadata")
        self.assertIsInstance(metadata, dict)
        self.assertIn(metadata.get("selection_reason"), {"coverage_gap", "coverage_extension", "stabilize_signal"})
        self.assertEqual(metadata.get("trigger_question_id"), opening_questions[-1]["question_id"])
        self.assertIsInstance(metadata.get("trigger_score"), float)

        latest_answered = next(
            item for item in latest_session["questions"] if item["question_id"] == opening_questions[-1]["question_id"]
        )
        self.assertIn(followup_question["question_id"], latest_answered.get("follow_up_ids", []))

    def test_adaptive_followup_remediates_same_competency_for_low_recent_score(self) -> None:
        _, job_spec_id = self._create_job_spec()
        _, candidate_id = self._create_candidate_profile()

        create_status, _, create_body = _request(
            self.app,
            method="POST",
            path="/v1/interview-sessions",
            body={"job_spec_id": job_spec_id, "candidate_id": candidate_id},
        )
        self.assertEqual(create_status, 201, create_body)
        session_id = create_body["data"]["session_id"]
        opening_questions = create_body["data"]["questions"]
        self.assertGreaterEqual(len(opening_questions), 1)

        latest_session = create_body["data"]
        for idx, question in enumerate(opening_questions, start=1):
            response = (
                "I built services and improved reliability by 22% while coordinating stakeholders."
                if idx < len(opening_questions)
                else "ok"
            )
            respond_status, _, respond_body = _request(
                self.app,
                method="POST",
                path=f"/v1/interview-sessions/{session_id}/responses",
                body={"question_id": question["question_id"], "response": response},
                headers={"Idempotency-Key": f"adaptive-low-{idx}"},
            )
            self.assertEqual(respond_status, 200, respond_body)
            latest_session = respond_body["data"]

        followup_question = latest_session["questions"][-1]
        self.assertGreater(len(latest_session["questions"]), len(opening_questions))
        self.assertEqual(followup_question["competency"], opening_questions[-1]["competency"])
        self.assertEqual(
            followup_question.get("planner_metadata", {}).get("selection_reason"),
            "low_score_remediation",
        )

        expected_difficulty = min(5, int(opening_questions[-1]["difficulty"]) + 1)
        self.assertEqual(int(followup_question["difficulty"]), expected_difficulty)

    def test_interview_session_multi_turn_snapshots_persist_until_completion(self) -> None:
        _, job_spec_id = self._create_job_spec()
        _, candidate_id = self._create_candidate_profile()

        create_status, _, create_body = _request(
            self.app,
            method="POST",
            path="/v1/interview-sessions",
            body={"job_spec_id": job_spec_id, "candidate_id": candidate_id},
        )
        self.assertEqual(create_status, 201, create_body)
        session_id = create_body["data"]["session_id"]
        latest_session = create_body["data"]
        expected_version = 1
        response_count = 0

        for _ in range(8):
            unanswered = [question for question in latest_session["questions"] if not str(question.get("response", "")).strip()]
            if not unanswered:
                break

            target_question = unanswered[0]
            response_count += 1
            respond_status, _, respond_body = _request(
                self.app,
                method="POST",
                path=f"/v1/interview-sessions/{session_id}/responses",
                body={
                    "question_id": target_question["question_id"],
                    "response": (
                        "I led delivery execution, aligned stakeholders, and improved reliability by 27% "
                        "while reducing incident volume."
                    ),
                },
                headers={"Idempotency-Key": f"session-complete-{response_count}"},
            )
            self.assertEqual(respond_status, 200, respond_body)
            latest_session = respond_body["data"]
            expected_version += 1
            self.assertEqual(int(latest_session["version"]), expected_version)

        self.assertEqual(latest_session["status"], "completed")
        self.assertTrue(all(str(question.get("response", "")).strip() for question in latest_session["questions"]))
        final_validation = self.validator.validate("InterviewSession", latest_session)
        self.assertTrue(final_validation.is_valid, f"InterviewSession validation failed: {final_validation.issues}")

        get_status, _, get_body = _request(
            self.app,
            method="GET",
            path=f"/v1/interview-sessions/{session_id}",
        )
        self.assertEqual(get_status, 200, get_body)
        persisted_snapshot = get_body["data"]
        self.assertEqual(persisted_snapshot["version"], latest_session["version"])
        self.assertEqual(persisted_snapshot["status"], "completed")
        self.assertEqual(persisted_snapshot["scores"], latest_session["scores"])
        self.assertEqual(persisted_snapshot["overall_score"], latest_session["overall_score"])
        get_validation = self.validator.validate("InterviewSession", persisted_snapshot)
        self.assertTrue(get_validation.is_valid, f"InterviewSession validation failed: {get_validation.issues}")

        with closing(sqlite3.connect(self.db_path)) as conn:
            row = conn.execute(
                """
                SELECT version, status, questions_json, scores_json, overall_score
                FROM interview_sessions
                WHERE session_id = ?
                """,
                (session_id,),
            ).fetchone()
            response_rows = conn.execute(
                """
                SELECT question_id, response_text, score
                FROM interview_session_responses
                WHERE session_id = ?
                ORDER BY created_at ASC
                """,
                (session_id,),
            ).fetchall()

        self.assertIsNotNone(row)
        assert row is not None
        self.assertEqual(int(row[0]), int(latest_session["version"]))
        self.assertEqual(str(row[1]), "completed")
        self.assertEqual(float(row[4]), float(latest_session["overall_score"]))

        persisted_questions = json.loads(str(row[2]))
        self.assertEqual(len(persisted_questions), len(latest_session["questions"]))
        persisted_scores = json.loads(str(row[3]))
        self.assertEqual(persisted_scores, latest_session["scores"])

        self.assertEqual(len(response_rows), response_count)
        for response_row in response_rows:
            self.assertTrue(response_row[0])
            self.assertTrue(response_row[1])
            self.assertGreaterEqual(float(response_row[2]), 0.0)
            self.assertLessEqual(float(response_row[2]), 100.0)

    def test_reviewer_override_followup_applies_with_audit_trail(self) -> None:
        _, job_spec_id = self._create_job_spec()
        _, candidate_id = self._create_candidate_profile()

        create_status, _, create_body = _request(
            self.app,
            method="POST",
            path="/v1/interview-sessions",
            body={"job_spec_id": job_spec_id, "candidate_id": candidate_id},
        )
        self.assertEqual(create_status, 201, create_body)
        session_id = create_body["data"]["session_id"]
        opening_questions = create_body["data"]["questions"]
        self.assertGreaterEqual(len(opening_questions), 1)

        latest_session = create_body["data"]
        current_version = int(latest_session["version"])
        override_key = "reviewer-override-key-001"
        override_payload = {
            "reviewer_id": "rev_001",
            "reason": "Candidate evidence suggests communication risk remains unresolved.",
            "competency": "skill.communication",
            "difficulty": 4,
        }

        for idx, question in enumerate(opening_questions, start=1):
            response_body: dict[str, Any] = {
                "question_id": question["question_id"],
                "response": (
                    "I led cross-team delivery and improved reliability by 20%."
                    if idx < len(opening_questions)
                    else "ok"
                ),
                "expected_version": current_version,
            }
            idempotency_key = f"reviewer-override-seed-{idx}"
            if idx == len(opening_questions):
                response_body["override_followup"] = override_payload
                idempotency_key = override_key

            respond_status, _, respond_body = _request(
                self.app,
                method="POST",
                path=f"/v1/interview-sessions/{session_id}/responses",
                body=response_body,
                headers={"Idempotency-Key": idempotency_key},
            )
            self.assertEqual(respond_status, 200, respond_body)
            latest_session = respond_body["data"]
            current_version += 1
            self.assertEqual(int(latest_session["version"]), current_version)

        self.assertGreater(len(latest_session["questions"]), len(opening_questions))
        followup_question = latest_session["questions"][-1]
        self.assertEqual(followup_question["competency"], "skill.communication")
        self.assertEqual(int(followup_question["difficulty"]), 4)

        planner_metadata = followup_question.get("planner_metadata", {})
        self.assertEqual(planner_metadata.get("selection_reason"), "reviewer_override")
        self.assertTrue(planner_metadata.get("override_applied"))
        self.assertEqual(planner_metadata.get("override_reviewer_id"), "rev_001")
        self.assertTrue(str(planner_metadata.get("override_reason", "")).strip())
        self.assertGreaterEqual(float(planner_metadata.get("override_trigger_confidence", 0.0)), 0.0)

        with closing(sqlite3.connect(self.db_path)) as conn:
            audit_row = conn.execute(
                """
                SELECT request_json
                FROM interview_session_responses
                WHERE session_id = ? AND idempotency_key = ?
                """,
                (session_id, override_key),
            ).fetchone()

        self.assertIsNotNone(audit_row)
        assert audit_row is not None
        request_json = json.loads(str(audit_row[0]))
        self.assertEqual(request_json.get("expected_version"), current_version - 1)
        self.assertEqual(request_json.get("override_followup", {}).get("reviewer_id"), "rev_001")
        self.assertEqual(request_json.get("override_followup", {}).get("competency"), "skill.communication")

    def test_append_interview_response_expected_version_conflict_returns_409(self) -> None:
        _, job_spec_id = self._create_job_spec()
        _, candidate_id = self._create_candidate_profile()

        create_status, _, create_body = _request(
            self.app,
            method="POST",
            path="/v1/interview-sessions",
            body={"job_spec_id": job_spec_id, "candidate_id": candidate_id},
        )
        self.assertEqual(create_status, 201, create_body)
        session_id = create_body["data"]["session_id"]

        conflict_status, _, conflict_body = _request(
            self.app,
            method="POST",
            path=f"/v1/interview-sessions/{session_id}/responses",
            body={
                "response": "I led a migration that improved reliability.",
                "expected_version": 99,
            },
            headers={"Idempotency-Key": "expected-version-conflict-001"},
        )
        self.assertEqual(conflict_status, 409, conflict_body)
        self.assertEqual(conflict_body["error"]["code"], "version_conflict")
        reasons = [detail.get("reason", "") for detail in conflict_body["error"].get("details", [])]
        self.assertTrue(any("current version is 1" in reason for reason in reasons))

    def test_interview_session_endpoints_validate_request_shape(self) -> None:
        missing_fields_status, _, missing_fields_body = _request(
            self.app,
            method="POST",
            path="/v1/interview-sessions",
            body={"candidate_id": "cand_missing"},
        )
        self.assertEqual(missing_fields_status, 400, missing_fields_body)
        self.assertEqual(missing_fields_body["error"]["code"], "invalid_request")

        _, job_spec_id = self._create_job_spec()
        _, candidate_id = self._create_candidate_profile()
        create_status, _, create_body = _request(
            self.app,
            method="POST",
            path="/v1/interview-sessions",
            body={"job_spec_id": job_spec_id, "candidate_id": candidate_id},
        )
        self.assertEqual(create_status, 201, create_body)
        session_id = create_body["data"]["session_id"]

        missing_header_status, _, missing_header_body = _request(
            self.app,
            method="POST",
            path=f"/v1/interview-sessions/{session_id}/responses",
            body={"response": "Answer without idempotency key."},
        )
        self.assertEqual(missing_header_status, 400, missing_header_body)
        self.assertEqual(missing_header_body["error"]["code"], "invalid_request")

        bad_body_status, _, bad_body_body = _request(
            self.app,
            method="POST",
            path=f"/v1/interview-sessions/{session_id}/responses",
            body={"response": ""},
            headers={"Idempotency-Key": "interview-response-bad-body"},
        )
        self.assertEqual(bad_body_status, 400, bad_body_body)
        self.assertEqual(bad_body_body["error"]["code"], "invalid_request")

        bad_override_status, _, bad_override_body = _request(
            self.app,
            method="POST",
            path=f"/v1/interview-sessions/{session_id}/responses",
            body={
                "response": "Answer with malformed override payload.",
                "override_followup": {
                    "reviewer_id": "",
                    "reason": "Needs override",
                    "competency": "skill.communication",
                    "difficulty": 9,
                },
            },
            headers={"Idempotency-Key": "interview-response-bad-override"},
        )
        self.assertEqual(bad_override_status, 400, bad_override_body)
        self.assertEqual(bad_override_body["error"]["code"], "invalid_request")

    def test_feedback_report_scores_are_deterministic_for_fixed_session(self) -> None:
        _, job_spec_id = self._create_job_spec()
        _, candidate_id = self._create_candidate_profile()

        create_status, _, create_body = _request(
            self.app,
            method="POST",
            path="/v1/interview-sessions",
            body={"job_spec_id": job_spec_id, "candidate_id": candidate_id},
        )
        self.assertEqual(create_status, 201, create_body)
        session_id = create_body["data"]["session_id"]
        first_question = create_body["data"]["questions"][0]

        respond_status, _, respond_body = _request(
            self.app,
            method="POST",
            path=f"/v1/interview-sessions/{session_id}/responses",
            body={
                "question_id": first_question["question_id"],
                "response": "I led a migration that reduced incident volume by 30% and improved reliability.",
            },
            headers={"Idempotency-Key": "feedback-deterministic-response-001"},
        )
        self.assertEqual(respond_status, 200, respond_body)

        first_status, _, first_body = _request(
            self.app,
            method="POST",
            path="/v1/feedback-reports",
            body={"session_id": session_id},
            headers={"Idempotency-Key": "feedback-deterministic-create-001"},
        )
        self.assertEqual(first_status, 201, first_body)
        first_report = first_body["data"]

        second_status, _, second_body = _request(
            self.app,
            method="POST",
            path="/v1/feedback-reports",
            body={"session_id": session_id},
            headers={"Idempotency-Key": "feedback-deterministic-create-002"},
        )
        self.assertEqual(second_status, 201, second_body)
        second_report = second_body["data"]

        self.assertIsInstance(first_report.get("overall_score"), (int, float))
        self.assertEqual(first_report.get("overall_score"), second_report.get("overall_score"))
        self.assertEqual(first_report.get("competency_scores"), second_report.get("competency_scores"))
        self.assertEqual(first_report.get("top_gaps"), second_report.get("top_gaps"))
        self.assertEqual(first_report.get("action_plan"), second_report.get("action_plan"))
        self.assertEqual(first_report.get("answer_rewrites"), second_report.get("answer_rewrites"))
        self.assertEqual(first_report.get("version"), 1)
        self.assertEqual(second_report.get("version"), 2)
        self.assertEqual(second_report.get("supersedes_feedback_report_id"), first_report.get("feedback_report_id"))

        action_plan = first_report.get("action_plan")
        self.assertIsInstance(action_plan, list)
        self.assertEqual(len(action_plan), 30)
        self.assertEqual([item.get("day") for item in action_plan], list(range(1, 31)))

        rewrites = first_report.get("answer_rewrites")
        self.assertIsInstance(rewrites, list)
        self.assertGreaterEqual(len(rewrites), 1)

    def test_feedback_report_expected_version_conflict_returns_409(self) -> None:
        _, job_spec_id = self._create_job_spec()
        _, candidate_id = self._create_candidate_profile()

        create_status, _, create_body = _request(
            self.app,
            method="POST",
            path="/v1/interview-sessions",
            body={"job_spec_id": job_spec_id, "candidate_id": candidate_id},
        )
        self.assertEqual(create_status, 201, create_body)
        session_id = create_body["data"]["session_id"]

        first_status, _, first_body = _request(
            self.app,
            method="POST",
            path="/v1/feedback-reports",
            body={"session_id": session_id},
            headers={"Idempotency-Key": "feedback-version-unit-initial"},
        )
        self.assertEqual(first_status, 201, first_body)
        self.assertEqual(first_body["data"].get("version"), 1)

        conflict_status, _, conflict_body = _request(
            self.app,
            method="POST",
            path="/v1/feedback-reports",
            body={"session_id": session_id, "expected_version": 0},
            headers={"Idempotency-Key": "feedback-version-unit-conflict"},
        )
        self.assertEqual(conflict_status, 409, conflict_body)
        self.assertEqual(conflict_body["error"]["code"], "version_conflict")
        reasons = [item.get("reason", "") for item in conflict_body["error"].get("details", [])]
        self.assertTrue(any("current version is 1" in reason for reason in reasons))

        next_status, _, next_body = _request(
            self.app,
            method="POST",
            path="/v1/feedback-reports",
            body={"session_id": session_id, "expected_version": 1},
            headers={"Idempotency-Key": "feedback-version-unit-next"},
        )
        self.assertEqual(next_status, 201, next_body)
        self.assertEqual(next_body["data"].get("version"), 2)
        self.assertEqual(
            next_body["data"].get("supersedes_feedback_report_id"),
            first_body["data"].get("feedback_report_id"),
        )

    def test_feedback_report_scores_fallback_to_question_history_when_scores_map_is_missing(self) -> None:
        _, job_spec_id = self._create_job_spec()
        _, candidate_id = self._create_candidate_profile()

        create_status, _, create_body = _request(
            self.app,
            method="POST",
            path="/v1/interview-sessions",
            body={"job_spec_id": job_spec_id, "candidate_id": candidate_id},
        )
        self.assertEqual(create_status, 201, create_body)
        session_id = create_body["data"]["session_id"]
        first_question = create_body["data"]["questions"][0]
        first_competency = str(first_question["competency"])

        respond_status, _, respond_body = _request(
            self.app,
            method="POST",
            path=f"/v1/interview-sessions/{session_id}/responses",
            body={
                "question_id": first_question["question_id"],
                "response": "I built services, improved reliability by 25%, and reduced p95 latency by 40%.",
            },
            headers={"Idempotency-Key": "feedback-fallback-response-001"},
        )
        self.assertEqual(respond_status, 200, respond_body)

        with closing(sqlite3.connect(self.db_path)) as conn:
            with conn:
                conn.execute(
                    """
                    UPDATE interview_sessions
                    SET scores_json = ?, overall_score = ?
                    WHERE session_id = ?
                    """,
                    ("{}", 0.0, session_id),
                )

        report_status, _, report_body = _request(
            self.app,
            method="POST",
            path="/v1/feedback-reports",
            body={"session_id": session_id},
            headers={"Idempotency-Key": "feedback-fallback-create-001"},
        )
        self.assertEqual(report_status, 201, report_body)
        report = report_body["data"]

        competency_scores = report.get("competency_scores")
        self.assertIsInstance(competency_scores, dict)
        self.assertIn(first_competency, competency_scores)
        assert isinstance(competency_scores, dict)
        self.assertGreater(float(competency_scores[first_competency]), 0.0)
        self.assertGreater(float(report.get("overall_score", 0.0)), 0.0)

    def test_feedback_report_root_cause_uses_quality_signals_with_stable_ordering(self) -> None:
        _, job_spec_id = self._create_job_spec()
        _, candidate_id = self._create_candidate_profile()

        create_status, _, create_body = _request(
            self.app,
            method="POST",
            path="/v1/interview-sessions",
            body={"job_spec_id": job_spec_id, "candidate_id": candidate_id},
        )
        self.assertEqual(create_status, 201, create_body)

        session_id = create_body["data"]["session_id"]
        latest_session = create_body["data"]
        turn_index = 0

        for _ in range(10):
            unanswered = [question for question in latest_session["questions"] if not str(question.get("response", "")).strip()]
            if not unanswered:
                break

            turn_index += 1
            target_question = unanswered[0]
            response_text = "ok"
            if turn_index > 1:
                response_text = (
                    "I led a migration that reduced incidents by 35%, improved uptime from 99.2% to 99.9%, "
                    "and aligned engineering and product stakeholders."
                )

            respond_status, _, respond_body = _request(
                self.app,
                method="POST",
                path=f"/v1/interview-sessions/{session_id}/responses",
                body={"question_id": target_question["question_id"], "response": response_text},
                headers={"Idempotency-Key": f"feedback-root-cause-turn-{turn_index}"},
            )
            self.assertEqual(respond_status, 200, respond_body)
            latest_session = respond_body["data"]
            if latest_session.get("status") == "completed":
                break

        self.assertEqual(latest_session.get("status"), "completed")

        first_status, _, first_body = _request(
            self.app,
            method="POST",
            path="/v1/feedback-reports",
            body={"session_id": session_id},
            headers={"Idempotency-Key": "feedback-root-cause-report-001"},
        )
        self.assertEqual(first_status, 201, first_body)
        first_report = first_body["data"]

        second_status, _, second_body = _request(
            self.app,
            method="POST",
            path="/v1/feedback-reports",
            body={"session_id": session_id},
            headers={"Idempotency-Key": "feedback-root-cause-report-002"},
        )
        self.assertEqual(second_status, 201, second_body)
        second_report = second_body["data"]

        self.assertEqual(first_report.get("top_gaps"), second_report.get("top_gaps"))
        top_gaps = first_report.get("top_gaps")
        self.assertIsInstance(top_gaps, list)
        self.assertGreaterEqual(len(top_gaps), 1)
        first_gap = top_gaps[0]
        self.assertIn(first_gap.get("severity"), {"high", "critical"})
        root_cause = str(first_gap.get("root_cause", "")).lower()
        self.assertTrue(
            any(fragment in root_cause for fragment in ["brief", "quantified", "below rubric", "missing"]),
            first_gap,
        )
        evidence = str(first_gap.get("evidence", ""))
        self.assertIn("score=", evidence)
        action_plan = first_report.get("action_plan")
        self.assertIsInstance(action_plan, list)
        self.assertEqual(len(action_plan), 30)
        rewrites = first_report.get("answer_rewrites")
        self.assertIsInstance(rewrites, list)
        self.assertGreaterEqual(len(rewrites), 1)

    def test_create_and_get_negotiation_plan_persists_schema_valid_row(self) -> None:
        _, candidate_id = self._create_candidate_profile()
        target_role = "Senior Backend Engineer"

        create_status, _, create_body = _request(
            self.app,
            method="POST",
            path="/v1/negotiation-plans",
            body={
                "candidate_id": candidate_id,
                "target_role": target_role,
                "current_base_salary": 155000,
                "target_base_salary": 180000,
                "compensation_currency": "usd",
                "offer_deadline_date": "2026-03-15",
            },
            headers={"Idempotency-Key": "negotiation-unit-create-001"},
        )
        self.assertEqual(create_status, 201, create_body)
        self.assertIsNone(create_body["error"])
        plan = create_body["data"]
        negotiation_plan_id = plan.get("negotiation_plan_id")
        self.assertIsInstance(negotiation_plan_id, str)
        self.assertTrue(negotiation_plan_id)
        assert isinstance(negotiation_plan_id, str)
        self.assertEqual(plan.get("candidate_id"), candidate_id)
        self.assertEqual(plan.get("target_role"), target_role)
        self.assertEqual(plan.get("offer_deadline_date"), "2026-03-15")
        compensation_targets = plan.get("compensation_targets")
        self.assertIsInstance(compensation_targets, dict)
        assert isinstance(compensation_targets, dict)
        self.assertEqual(compensation_targets.get("currency"), "USD")
        self.assertEqual(compensation_targets.get("current_base_salary"), 155000)
        self.assertEqual(compensation_targets.get("target_base_salary"), 180000)
        self.assertGreaterEqual(compensation_targets.get("anchor_base_salary", 0), 180000)
        self.assertGreaterEqual(compensation_targets.get("walk_away_base_salary", 0), 155000)
        self.assertIsInstance(plan.get("talking_points"), list)
        self.assertGreaterEqual(len(plan.get("talking_points", [])), 1)
        self.assertIsInstance(plan.get("follow_up_actions"), list)
        self.assertGreaterEqual(len(plan.get("follow_up_actions", [])), 1)

        validation = self.validator.validate("NegotiationPlan", plan)
        self.assertTrue(validation.is_valid, f"NegotiationPlan validation failed: {validation.issues}")

        with closing(sqlite3.connect(self.db_path)) as conn:
            row = conn.execute(
                """
                SELECT
                    negotiation_plan_id,
                    candidate_id,
                    target_role,
                    idempotency_key,
                    payload_json
                FROM negotiation_plans
                WHERE negotiation_plan_id = ?
                """,
                (negotiation_plan_id,),
            ).fetchone()
        self.assertIsNotNone(row)
        assert row is not None
        self.assertEqual(row[0], negotiation_plan_id)
        self.assertEqual(row[1], candidate_id)
        self.assertEqual(row[2], target_role)
        self.assertEqual(row[3], "negotiation-unit-create-001")
        payload = json.loads(str(row[4]))
        self.assertEqual(payload.get("negotiation_plan_id"), negotiation_plan_id)
        self.assertEqual(payload.get("candidate_id"), candidate_id)
        self.assertEqual(payload.get("target_role"), target_role)

        get_status, _, get_body = _request(
            self.app,
            method="GET",
            path=f"/v1/negotiation-plans/{negotiation_plan_id}",
        )
        self.assertEqual(get_status, 200, get_body)
        self.assertEqual(get_body["data"].get("negotiation_plan_id"), negotiation_plan_id)
        self.assertEqual(get_body["data"].get("compensation_targets"), plan.get("compensation_targets"))

    def test_negotiation_plan_endpoints_validate_request_shape_and_idempotency(self) -> None:
        _, candidate_id = self._create_candidate_profile()

        missing_header_status, _, missing_header_body = _request(
            self.app,
            method="POST",
            path="/v1/negotiation-plans",
            body={"candidate_id": candidate_id, "target_role": "Backend Engineer"},
        )
        self.assertEqual(missing_header_status, 400, missing_header_body)
        self.assertEqual(missing_header_body["error"]["code"], "invalid_request")

        invalid_body_status, _, invalid_body = _request(
            self.app,
            method="POST",
            path="/v1/negotiation-plans",
            body={},
            headers={"Idempotency-Key": "negotiation-unit-invalid-body-001"},
        )
        self.assertEqual(invalid_body_status, 400, invalid_body)
        self.assertEqual(invalid_body["error"]["code"], "invalid_request")

        invalid_salary_status, _, invalid_salary_body = _request(
            self.app,
            method="POST",
            path="/v1/negotiation-plans",
            body={
                "candidate_id": candidate_id,
                "target_role": "Backend Engineer",
                "current_base_salary": 150000,
                "target_base_salary": 140000,
            },
            headers={"Idempotency-Key": "negotiation-unit-invalid-salary-001"},
        )
        self.assertEqual(invalid_salary_status, 400, invalid_salary_body)
        self.assertEqual(invalid_salary_body["error"]["code"], "invalid_request")

        first_status, _, first_body = _request(
            self.app,
            method="POST",
            path="/v1/negotiation-plans",
            body={
                "candidate_id": candidate_id,
                "target_role": "Backend Engineer",
                "target_base_salary": 185000,
            },
            headers={"Idempotency-Key": "negotiation-unit-idempotency-001"},
        )
        self.assertEqual(first_status, 201, first_body)
        first_plan_id = first_body["data"].get("negotiation_plan_id")
        self.assertIsInstance(first_plan_id, str)
        self.assertTrue(first_plan_id)
        assert isinstance(first_plan_id, str)

        replay_status, _, replay_body = _request(
            self.app,
            method="POST",
            path="/v1/negotiation-plans",
            body={
                "candidate_id": candidate_id,
                "target_role": "Backend Engineer",
                "target_base_salary": 185000,
            },
            headers={"Idempotency-Key": "negotiation-unit-idempotency-001"},
        )
        self.assertEqual(replay_status, 201, replay_body)
        self.assertEqual(replay_body["data"].get("negotiation_plan_id"), first_plan_id)

        conflict_status, _, conflict_body = _request(
            self.app,
            method="POST",
            path="/v1/negotiation-plans",
            body={
                "candidate_id": candidate_id,
                "target_role": "Principal Backend Engineer",
                "target_base_salary": 200000,
            },
            headers={"Idempotency-Key": "negotiation-unit-idempotency-001"},
        )
        self.assertEqual(conflict_status, 409, conflict_body)
        self.assertEqual(conflict_body["error"]["code"], "idempotency_key_conflict")

        missing_candidate_status, _, missing_candidate_body = _request(
            self.app,
            method="POST",
            path="/v1/negotiation-plans",
            body={"candidate_id": "cand_missing_negotiation_unit_001", "target_role": "Backend Engineer"},
            headers={"Idempotency-Key": "negotiation-unit-missing-candidate-001"},
        )
        self.assertEqual(missing_candidate_status, 404, missing_candidate_body)
        self.assertEqual(missing_candidate_body["error"]["code"], "not_found")

        get_missing_status, _, get_missing_body = _request(
            self.app,
            method="GET",
            path="/v1/negotiation-plans/np_missing_unit_001",
        )
        self.assertEqual(get_missing_status, 404, get_missing_body)
        self.assertEqual(get_missing_body["error"]["code"], "not_found")

    def test_create_and_get_trajectory_plan_persists_schema_valid_row(self) -> None:
        _, candidate_id = self._create_candidate_profile()
        target_role = "Senior Backend Engineer"

        create_status, _, create_body = _request(
            self.app,
            method="POST",
            path="/v1/trajectory-plans",
            body={
                "candidate_id": candidate_id,
                "target_role": target_role,
            },
            headers={"Idempotency-Key": "trajectory-unit-create-001"},
        )
        self.assertEqual(create_status, 201, create_body)
        self.assertIsNone(create_body["error"])
        plan = create_body["data"]
        trajectory_plan_id = plan["trajectory_plan_id"]
        self.assertTrue(trajectory_plan_id)
        self.assertEqual(plan["candidate_id"], candidate_id)
        self.assertEqual(plan["target_role"], target_role)
        self.assertEqual(plan.get("version"), 1)
        self.assertIsNone(plan.get("supersedes_trajectory_plan_id"))
        progress_summary = plan.get("progress_summary")
        self.assertIsInstance(progress_summary, dict)
        assert isinstance(progress_summary, dict)
        self.assertEqual(progress_summary.get("history_counts", {}).get("snapshots"), 0)
        self.assertEqual(progress_summary.get("baseline"), {})
        self.assertEqual(progress_summary.get("current"), {})
        self.assertEqual(progress_summary.get("delta"), {})
        self.assertEqual(progress_summary.get("competency_trends"), [])

        validation = self.validator.validate("TrajectoryPlan", plan)
        self.assertTrue(validation.is_valid, f"TrajectoryPlan validation failed: {validation.issues}")

        with closing(sqlite3.connect(self.db_path)) as conn:
            row = conn.execute(
                """
                SELECT
                    trajectory_plan_id,
                    candidate_id,
                    target_role,
                    idempotency_key,
                    payload_json,
                    version,
                    supersedes_trajectory_plan_id
                FROM trajectory_plans
                WHERE trajectory_plan_id = ?
                """,
                (trajectory_plan_id,),
            ).fetchone()
        self.assertIsNotNone(row)
        assert row is not None
        self.assertEqual(row[0], trajectory_plan_id)
        self.assertEqual(row[1], candidate_id)
        self.assertEqual(row[2], target_role)
        self.assertEqual(row[3], "trajectory-unit-create-001")
        self.assertEqual(row[5], 1)
        self.assertIsNone(row[6])
        payload = json.loads(str(row[4]))
        self.assertEqual(payload.get("trajectory_plan_id"), trajectory_plan_id)
        self.assertEqual(payload.get("candidate_id"), candidate_id)
        self.assertEqual(payload.get("target_role"), target_role)
        self.assertEqual(payload.get("version"), 1)
        self.assertIsNone(payload.get("supersedes_trajectory_plan_id"))

        get_status, _, get_body = _request(
            self.app,
            method="GET",
            path=f"/v1/trajectory-plans/{trajectory_plan_id}",
        )
        self.assertEqual(get_status, 200, get_body)
        self.assertEqual(get_body["data"]["trajectory_plan_id"], trajectory_plan_id)
        self.assertEqual(get_body["data"]["milestones"], plan.get("milestones"))
        self.assertEqual(get_body["data"]["weekly_plan"], plan.get("weekly_plan"))
        self.assertEqual(get_body["data"]["progress_summary"], plan.get("progress_summary"))
        self.assertEqual(get_body["data"].get("version"), 1)
        self.assertIsNone(get_body["data"].get("supersedes_trajectory_plan_id"))

    def test_trajectory_progress_summary_is_deterministic_for_fixed_history(self) -> None:
        _, job_spec_id = self._create_job_spec()
        _, candidate_id = self._create_candidate_profile()

        create_session_status, _, create_session_body = _request(
            self.app,
            method="POST",
            path="/v1/interview-sessions",
            body={"job_spec_id": job_spec_id, "candidate_id": candidate_id},
        )
        self.assertEqual(create_session_status, 201, create_session_body)
        session_data = create_session_body["data"]
        session_id = session_data["session_id"]
        first_question = session_data["questions"][0]

        respond_status, _, respond_body = _request(
            self.app,
            method="POST",
            path=f"/v1/interview-sessions/{session_id}/responses",
            body={
                "question_id": first_question["question_id"],
                "response": "I led a migration that improved uptime to 99.9% and reduced incidents by 30%.",
            },
            headers={"Idempotency-Key": "trajectory-progress-seed-response-001"},
        )
        self.assertEqual(respond_status, 200, respond_body)

        feedback_status, _, feedback_body = _request(
            self.app,
            method="POST",
            path="/v1/feedback-reports",
            body={"session_id": session_id},
            headers={"Idempotency-Key": "trajectory-progress-seed-feedback-001"},
        )
        self.assertEqual(feedback_status, 201, feedback_body)

        first_plan_status, _, first_plan_body = _request(
            self.app,
            method="POST",
            path="/v1/trajectory-plans",
            body={"candidate_id": candidate_id, "target_role": "Senior Backend Engineer"},
            headers={"Idempotency-Key": "trajectory-progress-deterministic-001"},
        )
        self.assertEqual(first_plan_status, 201, first_plan_body)
        first_summary = first_plan_body["data"].get("progress_summary")
        self.assertIsInstance(first_summary, dict)
        assert isinstance(first_summary, dict)

        second_plan_status, _, second_plan_body = _request(
            self.app,
            method="POST",
            path="/v1/trajectory-plans",
            body={"candidate_id": candidate_id, "target_role": "Senior Backend Engineer"},
            headers={"Idempotency-Key": "trajectory-progress-deterministic-002"},
        )
        self.assertEqual(second_plan_status, 201, second_plan_body)
        second_summary = second_plan_body["data"].get("progress_summary")
        self.assertEqual(second_summary, first_summary)
        self.assertNotEqual(
            second_plan_body["data"].get("trajectory_plan_id"),
            first_plan_body["data"].get("trajectory_plan_id"),
        )
        self.assertEqual(first_plan_body["data"].get("version"), 1)
        self.assertEqual(second_plan_body["data"].get("version"), 2)
        self.assertEqual(
            second_plan_body["data"].get("supersedes_trajectory_plan_id"),
            first_plan_body["data"].get("trajectory_plan_id"),
        )
        self.assertEqual(second_plan_body["data"].get("milestones"), first_plan_body["data"].get("milestones"))
        self.assertEqual(second_plan_body["data"].get("weekly_plan"), first_plan_body["data"].get("weekly_plan"))

        history_counts = first_summary.get("history_counts")
        self.assertIsInstance(history_counts, dict)
        assert isinstance(history_counts, dict)
        self.assertEqual(history_counts.get("interview_sessions"), 1)
        self.assertEqual(history_counts.get("feedback_reports"), 1)
        self.assertEqual(history_counts.get("snapshots"), 2)

        baseline = first_summary.get("baseline")
        current = first_summary.get("current")
        delta = first_summary.get("delta")
        self.assertIsInstance(baseline, dict)
        self.assertIsInstance(current, dict)
        self.assertIsInstance(delta, dict)
        assert isinstance(baseline, dict)
        assert isinstance(current, dict)
        assert isinstance(delta, dict)
        self.assertIn(baseline.get("source_type"), {"interview_session", "feedback_report"})
        self.assertIn(current.get("source_type"), {"interview_session", "feedback_report"})
        baseline_overall = baseline.get("overall_score")
        current_overall = current.get("overall_score")
        self.assertIsInstance(baseline_overall, (int, float))
        self.assertIsInstance(current_overall, (int, float))
        expected_delta = round(float(current_overall) - float(baseline_overall), 2)
        self.assertEqual(delta.get("overall_score"), expected_delta)

        competency_trends = first_summary.get("competency_trends")
        self.assertIsInstance(competency_trends, list)
        self.assertGreaterEqual(len(competency_trends), 1)
        for entry in competency_trends:
            self.assertIsInstance(entry.get("competency"), str)
            self.assertIsInstance(entry.get("baseline_score"), (int, float))
            self.assertIsInstance(entry.get("current_score"), (int, float))
            self.assertIsInstance(entry.get("delta_score"), (int, float))
            self.assertIsInstance(entry.get("observation_count"), int)

        milestones = first_plan_body["data"].get("milestones")
        self.assertIsInstance(milestones, list)
        self.assertGreaterEqual(len(milestones or []), 3)
        assert isinstance(milestones, list)
        milestone_dates = [str(item.get("target_date", "")) for item in milestones if isinstance(item, dict)]
        self.assertEqual(milestone_dates, sorted(milestone_dates))

        weekly_plan = first_plan_body["data"].get("weekly_plan")
        self.assertIsInstance(weekly_plan, list)
        assert isinstance(weekly_plan, list)
        self.assertGreaterEqual(len(weekly_plan), 4)
        self.assertLessEqual(len(weekly_plan), 8)
        self.assertEqual([entry.get("week") for entry in weekly_plan], list(range(1, len(weekly_plan) + 1)))

        first_week_actions = " ".join(str(action) for action in weekly_plan[0].get("actions", [])).lower()
        self.assertIn("current=", first_week_actions)
        self.assertIn("target=", first_week_actions)
        self.assertIn("delta=", first_week_actions)

        top_risk = first_summary.get("top_risk_competencies", [])
        if isinstance(top_risk, list) and top_risk:
            expected_label = str(top_risk[0]).replace("skill.", "").replace("_", " ").lower()
            self.assertIn(expected_label, first_week_actions)

    def test_trajectory_plan_idempotency_replay_and_conflict(self) -> None:
        _, candidate_id = self._create_candidate_profile()

        first_status, _, first_body = _request(
            self.app,
            method="POST",
            path="/v1/trajectory-plans",
            body={
                "candidate_id": candidate_id,
                "target_role": "Staff Backend Engineer",
            },
            headers={"Idempotency-Key": "trajectory-unit-idempotency-001"},
        )
        self.assertEqual(first_status, 201, first_body)
        first_plan_id = first_body["data"]["trajectory_plan_id"]

        replay_status, _, replay_body = _request(
            self.app,
            method="POST",
            path="/v1/trajectory-plans",
            body={
                "candidate_id": candidate_id,
                "target_role": "Staff Backend Engineer",
            },
            headers={"Idempotency-Key": "trajectory-unit-idempotency-001"},
        )
        self.assertEqual(replay_status, 201, replay_body)
        self.assertEqual(replay_body["data"]["trajectory_plan_id"], first_plan_id)

        conflict_status, _, conflict_body = _request(
            self.app,
            method="POST",
            path="/v1/trajectory-plans",
            body={
                "candidate_id": candidate_id,
                "target_role": "Principal Backend Engineer",
            },
            headers={"Idempotency-Key": "trajectory-unit-idempotency-001"},
        )
        self.assertEqual(conflict_status, 409, conflict_body)
        self.assertEqual(conflict_body["error"]["code"], "idempotency_key_conflict")

    def test_trajectory_plan_regeneration_progression_and_expected_version_conflict(self) -> None:
        _, candidate_id = self._create_candidate_profile()
        target_role = "Staff Backend Engineer"

        first_status, _, first_body = _request(
            self.app,
            method="POST",
            path="/v1/trajectory-plans",
            body={"candidate_id": candidate_id, "target_role": target_role},
            headers={"Idempotency-Key": "trajectory-version-unit-initial"},
        )
        self.assertEqual(first_status, 201, first_body)
        first_plan = first_body["data"]
        first_plan_id = first_plan.get("trajectory_plan_id")
        self.assertEqual(first_plan.get("version"), 1)
        self.assertIsNone(first_plan.get("supersedes_trajectory_plan_id"))

        conflict_status, _, conflict_body = _request(
            self.app,
            method="POST",
            path="/v1/trajectory-plans",
            body={
                "candidate_id": candidate_id,
                "target_role": target_role,
                "regenerate": True,
                "expected_version": 0,
            },
            headers={"Idempotency-Key": "trajectory-version-unit-conflict-001"},
        )
        self.assertEqual(conflict_status, 409, conflict_body)
        self.assertEqual(conflict_body["error"]["code"], "version_conflict")
        reasons = [item.get("reason", "") for item in conflict_body["error"].get("details", [])]
        self.assertTrue(any("current version is 1" in reason for reason in reasons))

        second_status, _, second_body = _request(
            self.app,
            method="POST",
            path="/v1/trajectory-plans",
            body={
                "candidate_id": candidate_id,
                "target_role": target_role,
                "regenerate": True,
                "expected_version": 1,
            },
            headers={"Idempotency-Key": "trajectory-version-unit-next"},
        )
        self.assertEqual(second_status, 201, second_body)
        second_plan = second_body["data"]
        second_plan_id = second_plan.get("trajectory_plan_id")
        self.assertNotEqual(second_plan_id, first_plan_id)
        self.assertEqual(second_plan.get("version"), 2)
        self.assertEqual(second_plan.get("supersedes_trajectory_plan_id"), first_plan_id)

        second_replay_status, _, second_replay_body = _request(
            self.app,
            method="POST",
            path="/v1/trajectory-plans",
            body={
                "candidate_id": candidate_id,
                "target_role": target_role,
                "regenerate": True,
                "expected_version": 1,
            },
            headers={"Idempotency-Key": "trajectory-version-unit-next"},
        )
        self.assertEqual(second_replay_status, 201, second_replay_body)
        self.assertEqual(second_replay_body["data"].get("trajectory_plan_id"), second_plan_id)
        self.assertEqual(second_replay_body["data"].get("version"), 2)
        self.assertEqual(second_replay_body["data"].get("supersedes_trajectory_plan_id"), first_plan_id)

        stale_status, _, stale_body = _request(
            self.app,
            method="POST",
            path="/v1/trajectory-plans",
            body={
                "candidate_id": candidate_id,
                "target_role": target_role,
                "regenerate": True,
                "expected_version": 1,
            },
            headers={"Idempotency-Key": "trajectory-version-unit-stale"},
        )
        self.assertEqual(stale_status, 409, stale_body)
        self.assertEqual(stale_body["error"]["code"], "version_conflict")
        stale_reasons = [item.get("reason", "") for item in stale_body["error"].get("details", [])]
        self.assertTrue(any("current version is 2" in reason for reason in stale_reasons))

        get_status, _, get_body = _request(
            self.app,
            method="GET",
            path=f"/v1/trajectory-plans/{second_plan_id}",
        )
        self.assertEqual(get_status, 200, get_body)
        self.assertEqual(get_body["data"].get("version"), 2)
        self.assertEqual(get_body["data"].get("supersedes_trajectory_plan_id"), first_plan_id)

    def test_trajectory_plan_endpoints_validate_request_shape(self) -> None:
        _, candidate_id = self._create_candidate_profile()

        missing_header_status, _, missing_header_body = _request(
            self.app,
            method="POST",
            path="/v1/trajectory-plans",
            body={"candidate_id": candidate_id, "target_role": "Backend Engineer"},
        )
        self.assertEqual(missing_header_status, 400, missing_header_body)
        self.assertEqual(missing_header_body["error"]["code"], "invalid_request")

        invalid_body_status, _, invalid_body = _request(
            self.app,
            method="POST",
            path="/v1/trajectory-plans",
            body={},
            headers={"Idempotency-Key": "trajectory-unit-invalid-body-001"},
        )
        self.assertEqual(invalid_body_status, 400, invalid_body)
        self.assertEqual(invalid_body["error"]["code"], "invalid_request")

        invalid_expected_version_status, _, invalid_expected_version_body = _request(
            self.app,
            method="POST",
            path="/v1/trajectory-plans",
            body={"candidate_id": candidate_id, "target_role": "Backend Engineer", "expected_version": -1},
            headers={"Idempotency-Key": "trajectory-unit-invalid-expected-version-001"},
        )
        self.assertEqual(invalid_expected_version_status, 400, invalid_expected_version_body)
        self.assertEqual(invalid_expected_version_body["error"]["code"], "invalid_request")

        invalid_regenerate_status, _, invalid_regenerate_body = _request(
            self.app,
            method="POST",
            path="/v1/trajectory-plans",
            body={"candidate_id": candidate_id, "target_role": "Backend Engineer", "regenerate": "yes"},
            headers={"Idempotency-Key": "trajectory-unit-invalid-regenerate-001"},
        )
        self.assertEqual(invalid_regenerate_status, 400, invalid_regenerate_body)
        self.assertEqual(invalid_regenerate_body["error"]["code"], "invalid_request")

        missing_candidate_status, _, missing_candidate_body = _request(
            self.app,
            method="POST",
            path="/v1/trajectory-plans",
            body={"candidate_id": "cand_missing_unit_trajectory_001", "target_role": "Backend Engineer"},
            headers={"Idempotency-Key": "trajectory-unit-missing-candidate-001"},
        )
        self.assertEqual(missing_candidate_status, 404, missing_candidate_body)
        self.assertEqual(missing_candidate_body["error"]["code"], "not_found")

        get_missing_status, _, get_missing_body = _request(
            self.app,
            method="GET",
            path="/v1/trajectory-plans/tp_missing_unit_001",
        )
        self.assertEqual(get_missing_status, 404, get_missing_body)
        self.assertEqual(get_missing_body["error"]["code"], "not_found")

    def test_candidate_progress_dashboard_returns_deterministic_cards_and_latest_trajectory_context(self) -> None:
        _, job_spec_id = self._create_job_spec()
        _, candidate_id = self._create_candidate_profile()

        with closing(sqlite3.connect(self.db_path)) as conn:
            with conn:
                conn.execute(
                    """
                    INSERT INTO interview_sessions (
                        session_id,
                        job_spec_id,
                        candidate_id,
                        mode,
                        status,
                        questions_json,
                        scores_json,
                        overall_score,
                        root_cause_tags_json,
                        version,
                        created_at,
                        updated_at
                    )
                    VALUES (?, ?, ?, 'mock_interview', 'completed', ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "sess_dash_seed_001",
                        job_spec_id,
                        candidate_id,
                        "[]",
                        '{"skill.communication":55.0,"skill.execution":60.0,"skill.python":70.0}',
                        61.67,
                        "[]",
                        2,
                        "2026-02-20T10:00:00Z",
                        "2026-02-20T10:00:00Z",
                    ),
                )
                conn.execute(
                    """
                    INSERT INTO interview_sessions (
                        session_id,
                        job_spec_id,
                        candidate_id,
                        mode,
                        status,
                        questions_json,
                        scores_json,
                        overall_score,
                        root_cause_tags_json,
                        version,
                        created_at,
                        updated_at
                    )
                    VALUES (?, ?, ?, 'mock_interview', 'completed', ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "sess_dash_seed_002",
                        job_spec_id,
                        candidate_id,
                        "[]",
                        '{"skill.communication":75.0,"skill.execution":58.0,"skill.python":82.0}',
                        71.67,
                        "[]",
                        2,
                        "2026-02-22T10:00:00Z",
                        "2026-02-22T10:00:00Z",
                    ),
                )
                feedback_payload = json.dumps(
                    {
                        "feedback_report_id": "fb_dash_seed_001",
                        "session_id": "sess_dash_seed_002",
                        "competency_scores": {
                            "skill.communication": 78.0,
                            "skill.execution": 52.0,
                            "skill.python": 84.0,
                        },
                        "overall_score": 71.33,
                        "top_gaps": [],
                        "action_plan": [],
                        "generated_at": "2026-02-24T10:00:00Z",
                        "version": 1,
                    },
                    separators=(",", ":"),
                )
                conn.execute(
                    """
                    INSERT INTO feedback_reports (
                        feedback_report_id,
                        session_id,
                        idempotency_key,
                        request_json,
                        payload_json,
                        created_at,
                        updated_at,
                        version,
                        supersedes_feedback_report_id
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "fb_dash_seed_001",
                        "sess_dash_seed_002",
                        "feedback-dash-seed-001",
                        "{}",
                        feedback_payload,
                        "2026-02-24T10:00:00Z",
                        "2026-02-24T10:00:00Z",
                        1,
                        None,
                    ),
                )

        first_plan_status, _, first_plan_body = _request(
            self.app,
            method="POST",
            path="/v1/trajectory-plans",
            body={"candidate_id": candidate_id, "target_role": "Senior Backend Engineer"},
            headers={"Idempotency-Key": "dashboard-trajectory-initial-001"},
        )
        self.assertEqual(first_plan_status, 201, first_plan_body)
        first_plan_id = first_plan_body["data"]["trajectory_plan_id"]

        second_plan_status, _, second_plan_body = _request(
            self.app,
            method="POST",
            path="/v1/trajectory-plans",
            body={
                "candidate_id": candidate_id,
                "target_role": "Senior Backend Engineer",
                "regenerate": True,
                "expected_version": 1,
            },
            headers={"Idempotency-Key": "dashboard-trajectory-next-001"},
        )
        self.assertEqual(second_plan_status, 201, second_plan_body)
        second_plan_id = second_plan_body["data"]["trajectory_plan_id"]

        first_dashboard_status, _, first_dashboard_body = _request(
            self.app,
            method="GET",
            path=f"/v1/candidates/{candidate_id}/progress-dashboard?target_role=Senior%20Backend%20Engineer",
        )
        self.assertEqual(first_dashboard_status, 200, first_dashboard_body)
        first_dashboard = first_dashboard_body["data"]
        validation = self.validator.validate("CandidateProgressDashboard", first_dashboard)
        self.assertTrue(validation.is_valid, f"CandidateProgressDashboard validation failed: {validation.issues}")

        second_dashboard_status, _, second_dashboard_body = _request(
            self.app,
            method="GET",
            path=f"/v1/candidates/{candidate_id}/progress-dashboard?target_role=Senior%20Backend%20Engineer",
        )
        self.assertEqual(second_dashboard_status, 200, second_dashboard_body)
        self.assertEqual(second_dashboard_body["data"], first_dashboard)

        top_improving = first_dashboard["competency_trend_cards"]["top_improving"]
        self.assertEqual([entry["competency"] for entry in top_improving], ["skill.communication", "skill.python"])
        self.assertEqual([entry["trend_direction"] for entry in top_improving], ["improving", "improving"])

        top_risk = first_dashboard["competency_trend_cards"]["top_risk"]
        self.assertEqual([entry["competency"] for entry in top_risk], ["skill.execution", "skill.communication", "skill.python"])

        readiness = first_dashboard["readiness_signals"]
        self.assertEqual(readiness.get("snapshot_count"), 3)
        self.assertEqual(readiness.get("momentum"), "improving")
        self.assertIn(readiness.get("readiness_band"), {"developing", "strong"})

        latest_trajectory = first_dashboard["latest_trajectory_plan"]
        self.assertTrue(latest_trajectory.get("available"))
        self.assertEqual(latest_trajectory.get("trajectory_plan_id"), second_plan_id)
        self.assertEqual(latest_trajectory.get("version"), 2)
        self.assertEqual(latest_trajectory.get("supersedes_trajectory_plan_id"), first_plan_id)
        self.assertEqual(latest_trajectory.get("target_role"), "Senior Backend Engineer")

    def test_candidate_progress_dashboard_empty_history_and_query_validation(self) -> None:
        _, candidate_id = self._create_candidate_profile()

        dashboard_status, _, dashboard_body = _request(
            self.app,
            method="GET",
            path=f"/v1/candidates/{candidate_id}/progress-dashboard",
        )
        self.assertEqual(dashboard_status, 200, dashboard_body)
        dashboard = dashboard_body["data"]
        validation = self.validator.validate("CandidateProgressDashboard", dashboard)
        self.assertTrue(validation.is_valid, f"CandidateProgressDashboard validation failed: {validation.issues}")

        self.assertEqual(dashboard.get("candidate_id"), candidate_id)
        self.assertEqual(dashboard["progress_summary"].get("history_counts", {}).get("snapshots"), 0)
        self.assertEqual(dashboard["competency_trend_cards"].get("top_improving"), [])
        self.assertEqual(dashboard["competency_trend_cards"].get("top_risk"), [])
        self.assertEqual(dashboard["readiness_signals"].get("snapshot_count"), 0)
        self.assertEqual(dashboard["readiness_signals"].get("readiness_band"), "insufficient_data")
        self.assertEqual(dashboard["readiness_signals"].get("momentum"), "unknown")
        self.assertFalse(dashboard["latest_trajectory_plan"].get("available"))

        invalid_query_status, _, invalid_query_body = _request(
            self.app,
            method="GET",
            path=f"/v1/candidates/{candidate_id}/progress-dashboard?target_role=",
        )
        self.assertEqual(invalid_query_status, 400, invalid_query_body)
        self.assertEqual(invalid_query_body["error"]["code"], "invalid_request")

        missing_status, _, missing_body = _request(
            self.app,
            method="GET",
            path="/v1/candidates/cand_missing_dashboard_unit_001/progress-dashboard",
        )
        self.assertEqual(missing_status, 404, missing_body)
        self.assertEqual(missing_body["error"]["code"], "not_found")

    def test_post_and_get_candidate_ingestion_persists_row(self) -> None:
        payload = {
            "candidate_id": "cand_unit_001",
            "cv_text": (
                "Maya Rivera\n"
                "Senior Software Engineer\n"
                "Acme Corp | Senior Backend Engineer | 2021-02 - Present\n"
                "Built Python APIs and SQL workflows for ingestion pipelines.\n"
            ),
            "story_notes": ["Shipped workflow automation", "Improved incident MTTR"],
            "target_roles": ["Senior Backend Engineer"],
        }
        create_status, _, create_body = _request(
            self.app,
            method="POST",
            path="/v1/candidate-ingestions",
            body=payload,
            headers={"Idempotency-Key": "candidate-unit-001"},
        )
        self.assertEqual(create_status, 202, create_body)
        ingestion_id = create_body["data"]["ingestion_id"]
        self.assertTrue(ingestion_id)

        get_status, _, get_body = _request(
            self.app,
            method="GET",
            path=f"/v1/candidate-ingestions/{ingestion_id}",
        )
        self.assertEqual(get_status, 200, get_body)
        self.assertEqual(get_body["data"]["ingestion_id"], ingestion_id)
        self.assertEqual(get_body["data"]["status"], "queued")
        self.assertEqual(get_body["data"]["current_stage"], "queued")
        result = get_body["data"].get("result")
        self.assertIsInstance(result, dict)
        candidate_id = result.get("entity_id") if isinstance(result, dict) else None
        self.assertIsInstance(candidate_id, str)
        self.assertTrue(candidate_id)
        assert isinstance(candidate_id, str)

        with closing(sqlite3.connect(self.db_path)) as conn:
            row = conn.execute(
                """
                SELECT candidate_id, cv_text, cv_document_ref, story_notes_json, target_roles_json, status, result_candidate_id
                FROM candidate_ingestions
                WHERE ingestion_id = ?
                """,
                (ingestion_id,),
            ).fetchone()

        self.assertIsNotNone(row)
        assert row is not None
        self.assertEqual(row[0], payload["candidate_id"])
        self.assertEqual(row[1], payload["cv_text"])
        self.assertIsNone(row[2])
        self.assertEqual(json.loads(row[3]), payload["story_notes"])
        self.assertEqual(json.loads(row[4]), payload["target_roles"])
        self.assertEqual(row[5], "queued")
        self.assertEqual(row[6], candidate_id)

        with closing(sqlite3.connect(self.db_path)) as conn:
            candidate_profile_row = conn.execute(
                """
                SELECT candidate_id, summary, target_roles_json, experience_json, skills_json, parse_confidence, version
                FROM candidate_profiles
                WHERE candidate_id = ?
                """,
                (candidate_id,),
            ).fetchone()

        self.assertIsNotNone(candidate_profile_row)
        assert candidate_profile_row is not None
        candidate_profile_payload = {
            "candidate_id": candidate_profile_row[0],
            "summary": candidate_profile_row[1],
            "experience": json.loads(candidate_profile_row[3]),
            "skills": json.loads(candidate_profile_row[4]),
            "parse_confidence": float(candidate_profile_row[5]),
            "version": int(candidate_profile_row[6]),
        }
        target_roles = candidate_profile_row[2]
        if target_roles is not None:
            candidate_profile_payload["target_roles"] = json.loads(target_roles)

        validation = self.validator.validate("CandidateProfile", candidate_profile_payload)
        self.assertTrue(validation.is_valid, f"CandidateProfile validation failed: {validation.issues}")
        self.assertGreaterEqual(candidate_profile_payload["parse_confidence"], 0.0)
        self.assertLessEqual(candidate_profile_payload["parse_confidence"], 1.0)

        with closing(sqlite3.connect(self.db_path)) as conn:
            story_rows = conn.execute(
                """
                SELECT story_id, situation, task, action, result, competencies_json, metrics_json, evidence_quality
                FROM candidate_storybank
                WHERE candidate_id = ?
                ORDER BY created_at ASC, story_id ASC
                """,
                (candidate_id,),
            ).fetchall()

        self.assertGreaterEqual(len(story_rows), 1)
        first_story = story_rows[0]
        self.assertTrue(first_story[0])
        self.assertTrue(first_story[1])
        self.assertTrue(first_story[2])
        self.assertTrue(first_story[3])
        self.assertTrue(first_story[4])
        competencies = json.loads(first_story[5])
        self.assertIsInstance(competencies, list)
        self.assertGreaterEqual(len(competencies), 1)
        if first_story[6] is not None:
            metrics = json.loads(first_story[6])
            self.assertIsInstance(metrics, list)
        self.assertGreaterEqual(float(first_story[7]), 0.0)
        self.assertLessEqual(float(first_story[7]), 1.0)

    def test_candidate_ingestion_document_ref_generates_schema_valid_profile(self) -> None:
        create_status, _, create_body = _request(
            self.app,
            method="POST",
            path="/v1/candidate-ingestions",
            body={
                "candidate_id": "cand_docref_001",
                "cv_document_ref": "s3://candidate-resumes/cand_docref_001.pdf",
                "target_roles": ["Platform Engineer"],
            },
            headers={"Idempotency-Key": "candidate-docref-001"},
        )
        self.assertEqual(create_status, 202, create_body)
        ingestion_id = create_body["data"]["ingestion_id"]
        self.assertTrue(ingestion_id)

        get_status, _, get_body = _request(
            self.app,
            method="GET",
            path=f"/v1/candidate-ingestions/{ingestion_id}",
        )
        self.assertEqual(get_status, 200, get_body)
        result = get_body["data"].get("result")
        self.assertIsInstance(result, dict)
        candidate_id = result.get("entity_id") if isinstance(result, dict) else None
        self.assertIsInstance(candidate_id, str)
        self.assertTrue(candidate_id)
        assert isinstance(candidate_id, str)

        with closing(sqlite3.connect(self.db_path)) as conn:
            candidate_profile_row = conn.execute(
                """
                SELECT candidate_id, summary, target_roles_json, experience_json, skills_json, parse_confidence, version
                FROM candidate_profiles
                WHERE candidate_id = ?
                """,
                (candidate_id,),
            ).fetchone()

        self.assertIsNotNone(candidate_profile_row)
        assert candidate_profile_row is not None
        candidate_profile_payload = {
            "candidate_id": candidate_profile_row[0],
            "summary": candidate_profile_row[1],
            "experience": json.loads(candidate_profile_row[3]),
            "skills": json.loads(candidate_profile_row[4]),
            "parse_confidence": float(candidate_profile_row[5]),
            "version": int(candidate_profile_row[6]),
        }
        target_roles = candidate_profile_row[2]
        if target_roles is not None:
            candidate_profile_payload["target_roles"] = json.loads(target_roles)

        validation = self.validator.validate("CandidateProfile", candidate_profile_payload)
        self.assertTrue(validation.is_valid, f"CandidateProfile validation failed: {validation.issues}")

        with closing(sqlite3.connect(self.db_path)) as conn:
            story_rows = conn.execute(
                """
                SELECT story_id, competencies_json, evidence_quality
                FROM candidate_storybank
                WHERE candidate_id = ?
                ORDER BY created_at ASC, story_id ASC
                """,
                (candidate_id,),
            ).fetchall()

        self.assertGreaterEqual(len(story_rows), 1)
        for story_id, competencies_json, evidence_quality in story_rows:
            self.assertTrue(story_id)
            competencies = json.loads(competencies_json)
            self.assertIsInstance(competencies, list)
            self.assertGreaterEqual(len(competencies), 1)
            self.assertGreaterEqual(float(evidence_quality), 0.0)
            self.assertLessEqual(float(evidence_quality), 1.0)

    def test_get_candidate_profile_endpoint_returns_profile_with_storybank(self) -> None:
        create_status, _, create_body = _request(
            self.app,
            method="POST",
            path="/v1/candidate-ingestions",
            body={
                "candidate_id": "cand_profile_get_001",
                "cv_text": (
                    "Mina Park\n"
                    "Principal Engineer\n"
                    "Acme Corp | Staff Engineer | 2020-01 - Present\n"
                    "Reduced platform latency by 35% and improved reliability.\n"
                ),
                "story_notes": ["Led cross-functional reliability initiatives with 99.9% uptime."],
                "target_roles": ["Principal Engineer"],
            },
            headers={"Idempotency-Key": "candidate-profile-get-001"},
        )
        self.assertEqual(create_status, 202, create_body)
        ingestion_id = create_body["data"]["ingestion_id"]
        self.assertTrue(ingestion_id)

        status_status, _, status_body = _request(
            self.app,
            method="GET",
            path=f"/v1/candidate-ingestions/{ingestion_id}",
        )
        self.assertEqual(status_status, 200, status_body)
        result = status_body["data"].get("result")
        self.assertIsInstance(result, dict)
        candidate_id = result.get("entity_id") if isinstance(result, dict) else None
        self.assertIsInstance(candidate_id, str)
        self.assertTrue(candidate_id)
        assert isinstance(candidate_id, str)

        get_status, _, get_body = _request(
            self.app,
            method="GET",
            path=f"/v1/candidates/{candidate_id}/profile",
        )
        self.assertEqual(get_status, 200, get_body)
        self.assertIsNone(get_body["error"])

        profile_payload = get_body["data"]
        self.assertEqual(profile_payload["candidate_id"], candidate_id)
        self.assertIn("storybank", profile_payload)
        self.assertIsInstance(profile_payload["storybank"], list)
        self.assertGreaterEqual(len(profile_payload["storybank"]), 1)
        validation = self.validator.validate("CandidateProfile", profile_payload)
        self.assertTrue(validation.is_valid, f"CandidateProfile validation failed: {validation.issues}")

    def test_get_candidate_storybank_endpoint_supports_filters_and_cursor(self) -> None:
        create_status, _, create_body = _request(
            self.app,
            method="POST",
            path="/v1/candidate-ingestions",
            body={
                "candidate_id": "cand_story_get_001",
                "cv_text": (
                    "Jordan Lee\n"
                    "Staff Engineer\n"
                    "Acme Corp | Senior Engineer | 2019-01 - 2021-06\n"
                    "Globex Inc | Staff Engineer | 2021-07 - Present\n"
                ),
                "story_notes": [
                    "Led cross-functional migration and reduced incident volume by 30%.",
                    "Improved deployment success rate to 98%.",
                ],
                "target_roles": ["Staff Engineer"],
            },
            headers={"Idempotency-Key": "candidate-story-get-001"},
        )
        self.assertEqual(create_status, 202, create_body)
        ingestion_id = create_body["data"]["ingestion_id"]
        self.assertTrue(ingestion_id)

        status_status, _, status_body = _request(
            self.app,
            method="GET",
            path=f"/v1/candidate-ingestions/{ingestion_id}",
        )
        self.assertEqual(status_status, 200, status_body)
        result = status_body["data"].get("result")
        self.assertIsInstance(result, dict)
        candidate_id = result.get("entity_id") if isinstance(result, dict) else None
        self.assertIsInstance(candidate_id, str)
        self.assertTrue(candidate_id)
        assert isinstance(candidate_id, str)

        page_one_status, _, page_one_body = _request(
            self.app,
            method="GET",
            path=f"/v1/candidates/{candidate_id}/storybank?limit=1",
        )
        self.assertEqual(page_one_status, 200, page_one_body)
        page_one = page_one_body["data"]
        self.assertIsInstance(page_one["items"], list)
        self.assertEqual(len(page_one["items"]), 1)
        self.assertIsInstance(page_one["next_cursor"], str)
        self.assertTrue(page_one["next_cursor"])

        page_two_status, _, page_two_body = _request(
            self.app,
            method="GET",
            path=f"/v1/candidates/{candidate_id}/storybank?limit=1&cursor={page_one['next_cursor']}",
        )
        self.assertEqual(page_two_status, 200, page_two_body)
        page_two = page_two_body["data"]
        self.assertIsInstance(page_two["items"], list)
        self.assertGreaterEqual(len(page_two["items"]), 1)

        filtered_status, _, filtered_body = _request(
            self.app,
            method="GET",
            path=f"/v1/candidates/{candidate_id}/storybank?min_quality=0.8&competency=execution&limit=10",
        )
        self.assertEqual(filtered_status, 200, filtered_body)
        filtered_items = filtered_body["data"]["items"]
        self.assertIsInstance(filtered_items, list)
        self.assertGreaterEqual(len(filtered_items), 1)
        for story in filtered_items:
            self.assertGreaterEqual(float(story["evidence_quality"]), 0.8)
            self.assertIn("execution", story["competencies"])

        invalid_limit_status, _, invalid_limit_body = _request(
            self.app,
            method="GET",
            path=f"/v1/candidates/{candidate_id}/storybank?limit=0",
        )
        self.assertEqual(invalid_limit_status, 400, invalid_limit_body)
        self.assertEqual(invalid_limit_body["error"]["code"], "invalid_request")

    def test_candidate_retrieval_endpoints_return_not_found_for_unknown_candidate(self) -> None:
        profile_status, _, profile_body = _request(
            self.app,
            method="GET",
            path="/v1/candidates/cand_missing_001/profile",
        )
        self.assertEqual(profile_status, 404, profile_body)
        self.assertEqual(profile_body["error"]["code"], "not_found")

        storybank_status, _, storybank_body = _request(
            self.app,
            method="GET",
            path="/v1/candidates/cand_missing_001/storybank",
        )
        self.assertEqual(storybank_status, 404, storybank_body)
        self.assertEqual(storybank_body["error"]["code"], "not_found")

    def test_candidate_ingestion_idempotency_conflict_returns_409(self) -> None:
        first_status, _, first_body = _request(
            self.app,
            method="POST",
            path="/v1/candidate-ingestions",
            body={
                "candidate_id": "cand_unit_conflict",
                "cv_text": "First candidate request.",
            },
            headers={"Idempotency-Key": "candidate-unit-conflict-001"},
        )
        self.assertEqual(first_status, 202, first_body)

        conflict_status, _, conflict_body = _request(
            self.app,
            method="POST",
            path="/v1/candidate-ingestions",
            body={
                "candidate_id": "cand_unit_conflict",
                "cv_document_ref": "s3://bucket/other-resume.pdf",
            },
            headers={"Idempotency-Key": "candidate-unit-conflict-001"},
        )
        self.assertEqual(conflict_status, 409, conflict_body)
        self.assertIsNone(conflict_body["data"])
        self.assertEqual(conflict_body["error"]["code"], "idempotency_key_conflict")

    def test_candidate_ingestion_requires_exactly_one_cv_source(self) -> None:
        missing_status, _, missing_body = _request(
            self.app,
            method="POST",
            path="/v1/candidate-ingestions",
            body={"candidate_id": "cand_missing_cv"},
            headers={"Idempotency-Key": "candidate-unit-missing-cv"},
        )
        self.assertEqual(missing_status, 400, missing_body)
        self.assertEqual(missing_body["error"]["code"], "invalid_request")

        both_status, _, both_body = _request(
            self.app,
            method="POST",
            path="/v1/candidate-ingestions",
            body={
                "candidate_id": "cand_both_cv",
                "cv_text": "Candidate text",
                "cv_document_ref": "s3://bucket/resume.pdf",
            },
            headers={"Idempotency-Key": "candidate-unit-both-cv"},
        )
        self.assertEqual(both_status, 400, both_body)
        self.assertEqual(both_body["error"]["code"], "invalid_request")


if __name__ == "__main__":
    unittest.main(verbosity=2)
