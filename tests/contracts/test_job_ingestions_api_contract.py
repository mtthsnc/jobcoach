from __future__ import annotations

import json
import os
import re
import shlex
import sqlite3
import subprocess
import tempfile
import time
import unittest
import uuid
from contextlib import closing
from datetime import datetime
from pathlib import Path
from urllib import error, parse, request


ROOT = Path(__file__).resolve().parents[2]
MIGRATIONS_DIR = ROOT / "infra" / "migrations"
FIXTURES_ROOT = ROOT / "tests" / "contracts" / "fixtures" / "job_ingestions"

DEFAULT_API_BASE_URL = "http://127.0.0.1:8000"
API_PREFIX = "/v1"
READINESS_TIMEOUT_SECONDS = 15.0
REQUEST_TIMEOUT_SECONDS = 5.0

UP_MARKER = re.compile(r"^\s*--\s*\+goose\s+Up\s*$")
DOWN_MARKER = re.compile(r"^\s*--\s*\+goose\s+Down\s*$")


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
    if down_idx <= up_idx:
        raise RuntimeError(f"{path.name}: invalid migration marker order")

    up_sql = "".join(lines[up_idx + 1 : down_idx]).strip()
    if not up_sql:
        raise RuntimeError(f"{path.name}: Up section is empty")
    return up_sql + "\n"


def _bootstrap_sqlite_schema(db_path: Path) -> None:
    migration_files = sorted(MIGRATIONS_DIR.glob("*.sql"))
    if not migration_files:
        raise RuntimeError(f"No migrations found in {MIGRATIONS_DIR}")

    with closing(sqlite3.connect(db_path)) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        for migration in migration_files:
            conn.executescript(_parse_up_sql(migration))
        conn.commit()


def _load_fixture(name: str) -> dict:
    return json.loads((FIXTURES_ROOT / name).read_text(encoding="utf-8"))


class _LocalApiProcess:
    def __init__(self, command: list[str], base_url: str, db_path: Path):
        self._command = command
        self._base_url = base_url.rstrip("/")
        self._db_path = db_path
        self._process: subprocess.Popen[str] | None = None

    def start(self) -> None:
        parsed = parse.urlparse(self._base_url)
        env = os.environ.copy()
        env.setdefault("PORT", str(parsed.port or 8000))
        # Force the subprocess to use the bootstrapped contract DB even if parent
        # env (e.g. docker-compose) already defines persistent DB locations.
        env["JOBCOACH_DB_PATH"] = str(self._db_path)
        env["SQLITE_DB_PATH"] = str(self._db_path)
        env["DATABASE_URL"] = f"sqlite:///{self._db_path}"

        self._process = subprocess.Popen(
            self._command,
            cwd=ROOT,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            self._wait_until_ready()
        except Exception:
            self.stop()
            raise

    def stop(self) -> None:
        if self._process is None:
            return
        if self._process.poll() is None:
            self._process.terminate()
            try:
                self._process.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                self._process.kill()
                self._process.wait(timeout=2.0)
        if self._process.stdout:
            self._process.stdout.close()
        if self._process.stderr:
            self._process.stderr.close()
        self._process = None

    def _wait_until_ready(self) -> None:
        deadline = time.monotonic() + READINESS_TIMEOUT_SECONDS
        probe_path = "/health"
        probe_url = f"{self._base_url}{probe_path}"
        while time.monotonic() < deadline:
            if self._process is None:
                raise RuntimeError("API process has not been started")

            if self._process.poll() is not None:
                stdout, stderr = self._process.communicate(timeout=0.2)
                raise RuntimeError(
                    "Local API process exited before readiness probe succeeded.\n"
                    f"command={self._command}\nstdout:\n{stdout}\nstderr:\n{stderr}"
                )

            req = request.Request(url=probe_url, method="GET")
            try:
                with request.urlopen(req, timeout=0.5):
                    return
            except error.HTTPError:
                # Any HTTP response indicates the process is accepting requests.
                return
            except error.URLError:
                time.sleep(0.1)

        raise RuntimeError(
            f"Timed out waiting for local API readiness at {self._base_url}{probe_path}"
        )


def _decode_json_or_empty(raw: str) -> dict:
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    if isinstance(data, dict):
        return data
    return {}


def _request_json(
    base_url: str,
    method: str,
    path: str,
    body: dict | None = None,
    headers: dict[str, str] | None = None,
) -> tuple[int, dict]:
    payload = None if body is None else json.dumps(body).encode("utf-8")
    request_headers = {"Accept": "application/json"}
    if body is not None:
        request_headers["Content-Type"] = "application/json"
    if headers:
        request_headers.update(headers)

    req = request.Request(
        url=f"{base_url.rstrip('/')}{path}",
        data=payload,
        headers=request_headers,
        method=method,
    )

    try:
        with request.urlopen(req, timeout=REQUEST_TIMEOUT_SECONDS) as resp:
            raw = resp.read().decode("utf-8")
            return resp.status, _decode_json_or_empty(raw)
    except error.HTTPError as exc:
        raw = exc.read().decode("utf-8")
        return exc.code, _decode_json_or_empty(raw)


class JobIngestionApiContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        command_raw = os.getenv("JOBCOACH_API_CMD", "").strip()
        if not command_raw:
            raise unittest.SkipTest(
                "Set JOBCOACH_API_CMD to start the local API process for contract tests."
            )

        cls._tmpdir = tempfile.TemporaryDirectory(prefix="contract-job-ingestions-")
        cls.db_path = Path(cls._tmpdir.name) / "contract.sqlite3"
        _bootstrap_sqlite_schema(cls.db_path)

        cls.base_url = os.getenv("JOBCOACH_API_BASE_URL", DEFAULT_API_BASE_URL).rstrip("/")
        cls.api_process = _LocalApiProcess(
            command=shlex.split(command_raw),
            base_url=cls.base_url,
            db_path=cls.db_path,
        )
        cls.api_process.start()

    @classmethod
    def tearDownClass(cls) -> None:
        if hasattr(cls, "api_process"):
            cls.api_process.stop()
        if hasattr(cls, "_tmpdir"):
            cls._tmpdir.cleanup()

    def test_sqlite_schema_bootstrap_has_ingestion_tables(self) -> None:
        with closing(sqlite3.connect(self.db_path)) as conn:
            rows = conn.execute(
                """
                SELECT name
                FROM sqlite_master
                WHERE type = 'table'
                ORDER BY name
                """
            ).fetchall()

        table_names = {row[0] for row in rows}
        self.assertIn("job_ingestions", table_names)
        self.assertIn("candidate_ingestions", table_names)
        self.assertIn("eval_runs", table_names)
        self.assertIn("interview_sessions", table_names)
        self.assertIn("feedback_reports", table_names)
        self.assertIn("negotiation_plans", table_names)
        self.assertIn("trajectory_plans", table_names)

    def test_post_and_get_job_ingestion_contract(self) -> None:
        payload = _load_fixture("create_request.json")
        idempotency_key = f"contract-{uuid.uuid4()}"
        status, create_body = _request_json(
            self.base_url,
            "POST",
            f"{API_PREFIX}/job-ingestions",
            body=payload,
            headers={"Idempotency-Key": idempotency_key},
        )

        self.assertEqual(status, 202, create_body)
        ingestion_id = self._assert_ingestion_accepted_response(create_body)

        self._assert_ingestion_row_persisted(ingestion_id, payload, idempotency_key)

        get_status, get_body = self._wait_for_ingestion_status(ingestion_id)
        self.assertEqual(get_status, 200, get_body)
        self._assert_ingestion_status_response(get_body, ingestion_id)

    def test_post_and_get_candidate_ingestion_contract(self) -> None:
        payload = {
            "candidate_id": "cand_contract_001",
            "cv_text": (
                "Maya Rivera\n"
                "Senior Software Engineer\n"
                "Experience:\n"
                "- Built workflow APIs in Python and SQL.\n"
            ),
            "story_notes": [
                "Led incident response with cross-functional stakeholders.",
                "Reduced API p95 from 600ms to 280ms.",
            ],
            "target_roles": ["Staff Backend Engineer", "Platform Engineer"],
        }
        idempotency_key = f"candidate-contract-{uuid.uuid4()}"
        status, create_body = _request_json(
            self.base_url,
            "POST",
            f"{API_PREFIX}/candidate-ingestions",
            body=payload,
            headers={"Idempotency-Key": idempotency_key},
        )

        self.assertEqual(status, 202, create_body)
        ingestion_id = self._assert_ingestion_accepted_response(create_body)
        self._assert_candidate_ingestion_row_persisted(ingestion_id, payload, idempotency_key)

        get_status, get_body = self._wait_for_candidate_ingestion_status(ingestion_id)
        self.assertEqual(get_status, 200, get_body)
        self._assert_ingestion_status_response(get_body, ingestion_id)
        result = get_body.get("data", {}).get("result", {})
        candidate_entity_id = result.get("entity_id") if isinstance(result, dict) else None
        self.assertIsInstance(candidate_entity_id, str)
        self.assertTrue(candidate_entity_id)
        assert isinstance(candidate_entity_id, str)
        self._assert_candidate_profile_row_persisted(ingestion_id=ingestion_id, candidate_id=candidate_entity_id)
        self._assert_candidate_storybank_rows_persisted(candidate_id=candidate_entity_id)

    def test_candidate_ingestion_idempotency_conflict_contract(self) -> None:
        idempotency_key = f"candidate-conflict-{uuid.uuid4()}"
        first_payload = {
            "candidate_id": "cand_conflict_001",
            "cv_text": "Candidate profile text for first request.",
        }
        second_payload = {
            "candidate_id": "cand_conflict_001",
            "cv_document_ref": "s3://bucket/candidate-resume.pdf",
        }

        first_status, first_body = _request_json(
            self.base_url,
            "POST",
            f"{API_PREFIX}/candidate-ingestions",
            body=first_payload,
            headers={"Idempotency-Key": idempotency_key},
        )
        self.assertEqual(first_status, 202, first_body)

        second_status, second_body = _request_json(
            self.base_url,
            "POST",
            f"{API_PREFIX}/candidate-ingestions",
            body=second_payload,
            headers={"Idempotency-Key": idempotency_key},
        )
        self.assertEqual(second_status, 409, second_body)
        self.assertIsNone(second_body.get("data"))
        self.assertEqual(second_body.get("error", {}).get("code"), "idempotency_key_conflict")

    def test_taxonomy_normalize_contract(self) -> None:
        status, body = _request_json(
            self.base_url,
            "POST",
            f"{API_PREFIX}/taxonomy/normalize",
            body={"terms": ["Python", "GraphQL", "SQL", "python 3", "Python"]},
        )
        self.assertEqual(status, 200, body)
        self.assertIsNone(body.get("error"))
        data = body.get("data", {})
        self.assertEqual(data.get("taxonomy_version"), "m1-taxonomy-v1")
        mapped = data.get("mapped")
        self.assertIsInstance(mapped, list)
        mapped_by_input = {str(item.get("input")): item for item in mapped if isinstance(item, dict)}
        self.assertEqual(mapped_by_input.get("Python", {}).get("canonical"), "skill.python")
        self.assertEqual(mapped_by_input.get("python 3", {}).get("canonical"), "skill.python")
        self.assertEqual(mapped_by_input.get("SQL", {}).get("canonical"), "skill.sql")
        self.assertEqual(data.get("unmapped"), ["GraphQL"])
        self._assert_meta(body.get("meta", {}))
        self._assert_taxonomy_mapping_rows_persisted(
            expected={
                "python": ("skill.python", 1.0),
                "python 3": ("skill.python", 1.0),
                "sql": ("skill.sql", 1.0),
                "graphql": (None, 0.0),
            }
        )

    def test_taxonomy_normalize_validation_contract(self) -> None:
        status, body = _request_json(
            self.base_url,
            "POST",
            f"{API_PREFIX}/taxonomy/normalize",
            body={"terms": []},
        )
        self.assertEqual(status, 400, body)
        self.assertEqual(body.get("error", {}).get("code"), "invalid_request")
        self.assertIsInstance(body.get("error", {}).get("details"), list)

        status, body = _request_json(
            self.base_url,
            "POST",
            f"{API_PREFIX}/taxonomy/normalize",
            body={"terms": ["python", "", 123]},
        )
        self.assertEqual(status, 400, body)
        details = body.get("error", {}).get("details")
        self.assertIsInstance(details, list)
        assert isinstance(details, list)
        detail_fields = {str(item.get("field")) for item in details if isinstance(item, dict)}
        self.assertIn("terms[1]", detail_fields)
        self.assertIn("terms[2]", detail_fields)

    def test_run_eval_contract_persists_terminal_metrics(self) -> None:
        suite = "job_extraction_v1"
        idempotency_key = f"eval-run-create-{uuid.uuid4()}"
        status, body = _request_json(
            self.base_url,
            "POST",
            f"{API_PREFIX}/evals/run",
            body={"suite": suite},
            headers={"Idempotency-Key": idempotency_key},
        )
        self.assertEqual(status, 202, body)
        self.assertIsNone(body.get("error"))

        data = body.get("data", {})
        self.assertEqual(data.get("status"), "queued")
        eval_run_id = data.get("eval_run_id")
        self.assertIsInstance(eval_run_id, str)
        self.assertTrue(eval_run_id)
        assert isinstance(eval_run_id, str)
        self._assert_meta(body.get("meta", {}))

        self._assert_eval_run_row_persisted(
            eval_run_id=eval_run_id,
            suite=suite,
            idempotency_key=idempotency_key,
            request_payload={"suite": suite},
        )

    def test_run_eval_idempotency_replay_and_conflict_contract(self) -> None:
        idempotency_key = f"eval-run-idempotency-{uuid.uuid4()}"
        first_status, first_body = _request_json(
            self.base_url,
            "POST",
            f"{API_PREFIX}/evals/run",
            body={"suite": "feedback_quality_v1"},
            headers={"Idempotency-Key": idempotency_key},
        )
        self.assertEqual(first_status, 202, first_body)
        first_run_id = first_body.get("data", {}).get("eval_run_id")
        self.assertIsInstance(first_run_id, str)
        self.assertTrue(first_run_id)
        assert isinstance(first_run_id, str)

        replay_status, replay_body = _request_json(
            self.base_url,
            "POST",
            f"{API_PREFIX}/evals/run",
            body={"suite": "feedback_quality_v1"},
            headers={"Idempotency-Key": idempotency_key},
        )
        self.assertEqual(replay_status, 202, replay_body)
        self.assertEqual(replay_body.get("data", {}).get("eval_run_id"), first_run_id)
        self.assertEqual(replay_body.get("data", {}).get("status"), "queued")

        conflict_status, conflict_body = _request_json(
            self.base_url,
            "POST",
            f"{API_PREFIX}/evals/run",
            body={"suite": "trajectory_quality_v1"},
            headers={"Idempotency-Key": idempotency_key},
        )
        self.assertEqual(conflict_status, 409, conflict_body)
        self.assertEqual(conflict_body.get("error", {}).get("code"), "idempotency_key_conflict")

    def test_run_eval_validation_contract(self) -> None:
        missing_header_status, missing_header_body = _request_json(
            self.base_url,
            "POST",
            f"{API_PREFIX}/evals/run",
            body={"suite": "feedback_quality_v1"},
        )
        self.assertEqual(missing_header_status, 400, missing_header_body)
        self.assertEqual(missing_header_body.get("error", {}).get("code"), "invalid_request")

        invalid_suite_status, invalid_suite_body = _request_json(
            self.base_url,
            "POST",
            f"{API_PREFIX}/evals/run",
            body={"suite": "unknown_suite"},
            headers={"Idempotency-Key": f"eval-run-invalid-suite-{uuid.uuid4()}"},
        )
        self.assertEqual(invalid_suite_status, 400, invalid_suite_body)
        self.assertEqual(invalid_suite_body.get("error", {}).get("code"), "invalid_request")
        detail_fields = {
            str(item.get("field"))
            for item in invalid_suite_body.get("error", {}).get("details", [])
            if isinstance(item, dict)
        }
        self.assertIn("suite", detail_fields)

    def test_get_eval_run_contract_for_seeded_lifecycle_states(self) -> None:
        queued_eval_run_id = f"eval_contract_queued_{uuid.uuid4().hex}"
        running_eval_run_id = f"eval_contract_running_{uuid.uuid4().hex}"
        succeeded_eval_run_id = f"eval_contract_succeeded_{uuid.uuid4().hex}"
        failed_eval_run_id = f"eval_contract_failed_{uuid.uuid4().hex}"

        self._seed_eval_run_row(
            eval_run_id=queued_eval_run_id,
            suite="job_extraction_v1",
            status="queued",
            metrics={},
        )
        self._seed_eval_run_row(
            eval_run_id=running_eval_run_id,
            suite="candidate_parse_v1",
            status="running",
            metrics={},
            started_at="2026-03-01 00:00:01",
        )
        self._seed_eval_run_row(
            eval_run_id=succeeded_eval_run_id,
            suite="interview_relevance_v1",
            status="succeeded",
            metrics={
                "suite": "interview_relevance_v1",
                "passed": True,
                "aggregate": {"overall_relevance": 1.0},
                "failed_threshold_count": 0,
                "failed_threshold_metrics": [],
                "case_count": 3,
            },
            started_at="2026-03-01 00:00:02",
            completed_at="2026-03-01 00:00:03",
        )
        self._seed_eval_run_row(
            eval_run_id=failed_eval_run_id,
            suite="trajectory_quality_v1",
            status="failed",
            metrics={
                "suite": "trajectory_quality_v1",
                "passed": False,
                "aggregate": {"overall_trajectory_quality": 0.81},
                "failed_threshold_count": 1,
                "failed_threshold_metrics": ["overall_trajectory_quality"],
                "case_count": 4,
            },
            error_code="benchmark_threshold_failed",
            error_message="Threshold gate not satisfied",
            started_at="2026-03-01 00:00:04",
            completed_at="2026-03-01 00:00:05",
        )

        queued_status, queued_body = _request_json(
            self.base_url,
            "GET",
            f"{API_PREFIX}/evals/{queued_eval_run_id}",
        )
        self.assertEqual(queued_status, 200, queued_body)
        self.assertIsNone(queued_body.get("error"))
        queued_data = queued_body.get("data", {})
        self.assertEqual(queued_data.get("eval_run_id"), queued_eval_run_id)
        self.assertEqual(queued_data.get("suite"), "job_extraction_v1")
        self.assertEqual(queued_data.get("status"), "queued")
        self.assertEqual(queued_data.get("metrics"), {})
        self.assertNotIn("error", queued_data)
        self.assertIsInstance(queued_data.get("created_at"), str)
        self.assertNotIn("started_at", queued_data)
        self.assertNotIn("completed_at", queued_data)
        self._assert_meta(queued_body.get("meta", {}))

        running_status, running_body = _request_json(
            self.base_url,
            "GET",
            f"{API_PREFIX}/evals/{running_eval_run_id}",
        )
        self.assertEqual(running_status, 200, running_body)
        self.assertIsNone(running_body.get("error"))
        running_data = running_body.get("data", {})
        self.assertEqual(running_data.get("status"), "running")
        self.assertEqual(running_data.get("metrics"), {})
        self.assertIsInstance(running_data.get("started_at"), str)
        self.assertNotIn("completed_at", running_data)
        self._assert_meta(running_body.get("meta", {}))

        succeeded_status, succeeded_body = _request_json(
            self.base_url,
            "GET",
            f"{API_PREFIX}/evals/{succeeded_eval_run_id}",
        )
        self.assertEqual(succeeded_status, 200, succeeded_body)
        self.assertIsNone(succeeded_body.get("error"))
        succeeded_data = succeeded_body.get("data", {})
        self.assertEqual(succeeded_data.get("status"), "succeeded")
        self.assertEqual(succeeded_data.get("suite"), "interview_relevance_v1")
        self.assertTrue(succeeded_data.get("metrics", {}).get("passed"))
        self.assertIsInstance(succeeded_data.get("completed_at"), str)
        self.assertNotIn("error", succeeded_data)
        self._assert_meta(succeeded_body.get("meta", {}))

        failed_status, failed_body = _request_json(
            self.base_url,
            "GET",
            f"{API_PREFIX}/evals/{failed_eval_run_id}",
        )
        self.assertEqual(failed_status, 200, failed_body)
        self.assertIsNone(failed_body.get("error"))
        failed_data = failed_body.get("data", {})
        self.assertEqual(failed_data.get("status"), "failed")
        self.assertFalse(failed_data.get("metrics", {}).get("passed"))
        self.assertEqual(
            failed_data.get("error"),
            {"code": "benchmark_threshold_failed", "message": "Threshold gate not satisfied"},
        )
        self.assertIsInstance(failed_data.get("completed_at"), str)
        self._assert_meta(failed_body.get("meta", {}))

    def test_get_eval_run_not_found_and_method_path_validation_contract(self) -> None:
        missing_status, missing_body = _request_json(
            self.base_url,
            "GET",
            f"{API_PREFIX}/evals/eval_missing_001",
        )
        self.assertEqual(missing_status, 404, missing_body)
        self.assertEqual(missing_body.get("error", {}).get("code"), "not_found")
        self._assert_meta(missing_body.get("meta", {}))

        invalid_method_status, invalid_method_body = _request_json(
            self.base_url,
            "POST",
            f"{API_PREFIX}/evals/eval_method_001",
        )
        self.assertEqual(invalid_method_status, 405, invalid_method_body)
        self.assertEqual(invalid_method_body.get("error", {}).get("code"), "method_not_allowed")
        self._assert_meta(invalid_method_body.get("meta", {}))

        missing_id_status, missing_id_body = _request_json(
            self.base_url,
            "GET",
            f"{API_PREFIX}/evals/",
        )
        self.assertEqual(missing_id_status, 404, missing_id_body)
        self.assertEqual(missing_id_body.get("error", {}).get("code"), "not_found")
        self._assert_meta(missing_id_body.get("meta", {}))

        slashy_id_status, slashy_id_body = _request_json(
            self.base_url,
            "GET",
            f"{API_PREFIX}/evals/run/extra",
        )
        self.assertEqual(slashy_id_status, 404, slashy_id_body)
        self.assertEqual(slashy_id_body.get("error", {}).get("code"), "not_found")
        self._assert_meta(slashy_id_body.get("meta", {}))

    def test_get_candidate_profile_and_storybank_contract(self) -> None:
        payload = {
            "candidate_id": "cand_contract_retrieval_001",
            "cv_text": (
                "Alex Kim\n"
                "Staff Engineer\n"
                "Acme Corp | Senior Engineer | 2018-01 - 2021-12\n"
                "Globex Inc | Staff Engineer | 2022-01 - Present\n"
            ),
            "story_notes": [
                "Led cross-functional reliability program with 99.9% uptime.",
                "Improved deployment success rate by 25%.",
            ],
            "target_roles": ["Staff Engineer"],
        }
        idempotency_key = f"candidate-retrieval-{uuid.uuid4()}"
        create_status, create_body = _request_json(
            self.base_url,
            "POST",
            f"{API_PREFIX}/candidate-ingestions",
            body=payload,
            headers={"Idempotency-Key": idempotency_key},
        )
        self.assertEqual(create_status, 202, create_body)
        ingestion_id = self._assert_ingestion_accepted_response(create_body)

        get_status, get_body = self._wait_for_candidate_ingestion_status(ingestion_id)
        self.assertEqual(get_status, 200, get_body)
        result = get_body.get("data", {}).get("result", {})
        candidate_entity_id = result.get("entity_id") if isinstance(result, dict) else None
        self.assertIsInstance(candidate_entity_id, str)
        self.assertTrue(candidate_entity_id)
        assert isinstance(candidate_entity_id, str)

        profile_status, profile_body = _request_json(
            self.base_url,
            "GET",
            f"{API_PREFIX}/candidates/{candidate_entity_id}/profile",
        )
        self.assertEqual(profile_status, 200, profile_body)
        profile_data = profile_body.get("data", {})
        self.assertEqual(profile_data.get("candidate_id"), candidate_entity_id)
        self.assertIn("storybank", profile_data)
        self.assertIsInstance(profile_data.get("storybank"), list)
        self.assertGreaterEqual(len(profile_data.get("storybank", [])), 1)

        storybank_status, storybank_body = _request_json(
            self.base_url,
            "GET",
            f"{API_PREFIX}/candidates/{candidate_entity_id}/storybank?limit=1&competency=execution&min_quality=0.6",
        )
        self.assertEqual(storybank_status, 200, storybank_body)
        storybank_data = storybank_body.get("data", {})
        self.assertIsInstance(storybank_data.get("items"), list)
        self.assertGreaterEqual(len(storybank_data.get("items", [])), 1)
        self.assertIn("next_cursor", storybank_data)
        first_story = storybank_data["items"][0]
        self.assertIn("execution", first_story.get("competencies", []))
        self.assertGreaterEqual(float(first_story.get("evidence_quality", 0)), 0.6)

        next_cursor = storybank_data.get("next_cursor")
        if isinstance(next_cursor, str) and next_cursor:
            page_two_status, page_two_body = _request_json(
                self.base_url,
                "GET",
                f"{API_PREFIX}/candidates/{candidate_entity_id}/storybank?limit=1&cursor={next_cursor}",
            )
            self.assertEqual(page_two_status, 200, page_two_body)
            self.assertIsInstance(page_two_body.get("data", {}).get("items"), list)

    def test_patch_job_spec_review_conflict_contract(self) -> None:
        create_payload = {
            "source_type": "text",
            "source_value": (
                "Backend Engineer\n"
                "Responsibilities:\n"
                "- Build Python services.\n"
                "Requirements:\n"
                "- Strong SQL.\n"
            ),
        }
        idempotency_key = f"review-contract-{uuid.uuid4()}"
        status, create_body = _request_json(
            self.base_url,
            "POST",
            f"{API_PREFIX}/job-ingestions",
            body=create_payload,
            headers={"Idempotency-Key": idempotency_key},
        )
        self.assertEqual(status, 202, create_body)
        ingestion_id = self._assert_ingestion_accepted_response(create_body)

        get_status, get_body = self._wait_for_ingestion_status(ingestion_id)
        self.assertEqual(get_status, 200, get_body)
        data = get_body.get("data", {})
        result = data.get("result", {}) if isinstance(data, dict) else {}
        job_spec_id = result.get("entity_id") if isinstance(result, dict) else None
        self.assertIsInstance(job_spec_id, str)
        self.assertTrue(job_spec_id)
        assert isinstance(job_spec_id, str)

        review_path = f"{API_PREFIX}/job-specs/{job_spec_id}/review"
        first_status, first_body = _request_json(
            self.base_url,
            "PATCH",
            review_path,
            body={
                "expected_version": 1,
                "patch": {"role_title": "Senior Backend Engineer"},
            },
        )
        self.assertEqual(first_status, 200, first_body)
        self.assertEqual(first_body.get("data", {}).get("version"), 2)

        conflict_status, conflict_body = _request_json(
            self.base_url,
            "PATCH",
            review_path,
            body={
                "expected_version": 1,
                "patch": {"role_title": "Principal Backend Engineer"},
            },
        )
        self.assertEqual(conflict_status, 409, conflict_body)
        self.assertIsNone(conflict_body.get("data"))
        self.assertEqual(conflict_body.get("error", {}).get("code"), "version_conflict")

    def test_create_and_get_interview_session_contract(self) -> None:
        job_spec_id = self._create_job_spec_entity_for_interview()
        candidate_id = self._create_candidate_entity_for_interview()

        create_status, create_body = _request_json(
            self.base_url,
            "POST",
            f"{API_PREFIX}/interview-sessions",
            body={
                "job_spec_id": job_spec_id,
                "candidate_id": candidate_id,
                "mode": "mock_interview",
            },
        )
        self.assertEqual(create_status, 201, create_body)
        session_data = create_body.get("data", {})
        session_id = session_data.get("session_id")
        self.assertIsInstance(session_id, str)
        self.assertTrue(session_id)
        assert isinstance(session_id, str)
        self.assertEqual(session_data.get("job_spec_id"), job_spec_id)
        self.assertEqual(session_data.get("candidate_id"), candidate_id)
        self.assertIsInstance(session_data.get("questions"), list)
        self.assertGreaterEqual(len(session_data.get("questions", [])), 1)
        ranking_positions = []
        for question in session_data.get("questions", []):
            metadata = question.get("planner_metadata")
            self.assertIsInstance(metadata, dict)
            self.assertEqual(metadata.get("source_competency"), question.get("competency"))
            self.assertIsInstance(metadata.get("ranking_position"), int)
            self.assertIsInstance(metadata.get("deterministic_confidence"), float)
            ranking_positions.append(int(metadata["ranking_position"]))
        self.assertEqual(ranking_positions, list(range(1, len(ranking_positions) + 1)))

        second_create_status, second_create_body = _request_json(
            self.base_url,
            "POST",
            f"{API_PREFIX}/interview-sessions",
            body={
                "job_spec_id": job_spec_id,
                "candidate_id": candidate_id,
                "mode": "mock_interview",
            },
        )
        self.assertEqual(second_create_status, 201, second_create_body)

        def signature(questions: list[dict]) -> list[tuple]:
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

        self.assertEqual(
            signature(session_data.get("questions", [])),
            signature(second_create_body.get("data", {}).get("questions", [])),
        )

        get_status, get_body = _request_json(
            self.base_url,
            "GET",
            f"{API_PREFIX}/interview-sessions/{session_id}",
        )
        self.assertEqual(get_status, 200, get_body)
        self.assertEqual(get_body.get("data", {}).get("session_id"), session_id)
        self.assertEqual(get_body.get("data", {}).get("job_spec_id"), job_spec_id)
        self.assertEqual(get_body.get("data", {}).get("candidate_id"), candidate_id)

        self._assert_interview_session_row_persisted(session_id=session_id, job_spec_id=job_spec_id, candidate_id=candidate_id)

    def test_append_interview_response_contract_with_idempotency(self) -> None:
        job_spec_id = self._create_job_spec_entity_for_interview()
        candidate_id = self._create_candidate_entity_for_interview()
        create_status, create_body = _request_json(
            self.base_url,
            "POST",
            f"{API_PREFIX}/interview-sessions",
            body={"job_spec_id": job_spec_id, "candidate_id": candidate_id},
        )
        self.assertEqual(create_status, 201, create_body)
        session_id = create_body.get("data", {}).get("session_id")
        self.assertIsInstance(session_id, str)
        self.assertTrue(session_id)
        assert isinstance(session_id, str)

        response_payload = {
            "response": "I led a migration that improved uptime to 99.9% and reduced incidents by 30%.",
        }
        update_status, update_body = _request_json(
            self.base_url,
            "POST",
            f"{API_PREFIX}/interview-sessions/{session_id}/responses",
            body=response_payload,
            headers={"Idempotency-Key": "contract-interview-response-001"},
        )
        self.assertEqual(update_status, 200, update_body)
        self.assertEqual(update_body.get("data", {}).get("session_id"), session_id)
        self.assertGreaterEqual(float(update_body.get("data", {}).get("overall_score", 0.0)), 0.0)
        self.assertLessEqual(float(update_body.get("data", {}).get("overall_score", 0.0)), 100.0)

        replay_status, replay_body = _request_json(
            self.base_url,
            "POST",
            f"{API_PREFIX}/interview-sessions/{session_id}/responses",
            body=response_payload,
            headers={"Idempotency-Key": "contract-interview-response-001"},
        )
        self.assertEqual(replay_status, 200, replay_body)

        conflict_status, conflict_body = _request_json(
            self.base_url,
            "POST",
            f"{API_PREFIX}/interview-sessions/{session_id}/responses",
            body={"response": "Different response payload for same idempotency key."},
            headers={"Idempotency-Key": "contract-interview-response-001"},
        )
        self.assertEqual(conflict_status, 409, conflict_body)
        self.assertEqual(conflict_body.get("error", {}).get("code"), "idempotency_key_conflict")

        self._assert_interview_response_row_persisted(session_id=session_id, idempotency_key="contract-interview-response-001")

    def test_adaptive_followup_selection_contract(self) -> None:
        job_spec_id = self._create_job_spec_entity_for_interview()
        candidate_id = self._create_candidate_entity_for_interview()
        create_status, create_body = _request_json(
            self.base_url,
            "POST",
            f"{API_PREFIX}/interview-sessions",
            body={"job_spec_id": job_spec_id, "candidate_id": candidate_id},
        )
        self.assertEqual(create_status, 201, create_body)
        session_data = create_body.get("data", {})
        session_id = session_data.get("session_id")
        self.assertIsInstance(session_id, str)
        self.assertTrue(session_id)
        assert isinstance(session_id, str)

        opening_questions = session_data.get("questions", [])
        self.assertIsInstance(opening_questions, list)
        self.assertGreaterEqual(len(opening_questions), 1)

        latest_session = session_data
        for idx, question in enumerate(opening_questions, start=1):
            update_status, update_body = _request_json(
                self.base_url,
                "POST",
                f"{API_PREFIX}/interview-sessions/{session_id}/responses",
                body={
                    "question_id": question.get("question_id"),
                    "response": (
                        "I led a migration that improved uptime to 99.9%, reduced latency by 35%, "
                        "and stabilized deployment quality."
                    ),
                },
                headers={"Idempotency-Key": f"contract-adaptive-followup-{idx}"},
            )
            self.assertEqual(update_status, 200, update_body)
            latest_session = update_body.get("data", {})

        latest_questions = latest_session.get("questions", [])
        self.assertGreater(len(latest_questions), len(opening_questions), latest_session)
        followup = latest_questions[-1]
        self.assertNotEqual(followup.get("competency"), opening_questions[-1].get("competency"))
        self.assertGreaterEqual(int(followup.get("difficulty", 0)), 1)
        self.assertLessEqual(int(followup.get("difficulty", 0)), 5)

        planner_metadata = followup.get("planner_metadata")
        self.assertIsInstance(planner_metadata, dict)
        self.assertIn(
            planner_metadata.get("selection_reason"),
            {"coverage_gap", "coverage_extension", "stabilize_signal"},
        )
        self.assertEqual(planner_metadata.get("trigger_question_id"), opening_questions[-1].get("question_id"))

    def test_interview_session_completion_snapshots_contract(self) -> None:
        job_spec_id = self._create_job_spec_entity_for_interview()
        candidate_id = self._create_candidate_entity_for_interview()
        create_status, create_body = _request_json(
            self.base_url,
            "POST",
            f"{API_PREFIX}/interview-sessions",
            body={"job_spec_id": job_spec_id, "candidate_id": candidate_id},
        )
        self.assertEqual(create_status, 201, create_body)
        session = create_body.get("data", {})
        session_id = session.get("session_id")
        self.assertIsInstance(session_id, str)
        self.assertTrue(session_id)
        assert isinstance(session_id, str)

        expected_version = int(session.get("version", 1))
        turn_count = 0
        for _ in range(8):
            unanswered = [
                question for question in session.get("questions", []) if not str(question.get("response", "")).strip()
            ]
            if not unanswered:
                break

            turn_count += 1
            target = unanswered[0]
            update_status, update_body = _request_json(
                self.base_url,
                "POST",
                f"{API_PREFIX}/interview-sessions/{session_id}/responses",
                body={
                    "question_id": target.get("question_id"),
                    "response": (
                        "I led delivery work, improved reliability by 24%, and aligned "
                        "cross-functional stakeholders to complete migrations safely."
                    ),
                },
                headers={"Idempotency-Key": f"contract-session-complete-{turn_count}"},
            )
            self.assertEqual(update_status, 200, update_body)
            session = update_body.get("data", {})
            expected_version += 1
            self.assertEqual(int(session.get("version", 0)), expected_version)

        self.assertEqual(session.get("status"), "completed", session)
        self.assertTrue(all(str(item.get("response", "")).strip() for item in session.get("questions", [])))
        self.assertGreaterEqual(turn_count, 3)

        get_status, get_body = _request_json(
            self.base_url,
            "GET",
            f"{API_PREFIX}/interview-sessions/{session_id}",
        )
        self.assertEqual(get_status, 200, get_body)
        snapshot = get_body.get("data", {})
        self.assertEqual(snapshot.get("status"), "completed")
        self.assertEqual(snapshot.get("version"), session.get("version"))
        self.assertEqual(snapshot.get("scores"), session.get("scores"))
        self.assertEqual(snapshot.get("overall_score"), session.get("overall_score"))
        self.assertTrue(all(str(item.get("response", "")).strip() for item in snapshot.get("questions", [])))

        with closing(sqlite3.connect(self.db_path)) as conn:
            row = conn.execute(
                """
                SELECT version, status, overall_score
                FROM interview_sessions
                WHERE session_id = ?
                """,
                (session_id,),
            ).fetchone()
            response_rows = conn.execute(
                """
                SELECT idempotency_key, question_id, response_text, score
                FROM interview_session_responses
                WHERE session_id = ?
                ORDER BY created_at ASC
                """,
                (session_id,),
            ).fetchall()

        self.assertIsNotNone(row)
        assert row is not None
        self.assertEqual(int(row[0]), int(snapshot.get("version", 0)))
        self.assertEqual(str(row[1]), "completed")
        self.assertEqual(float(row[2]), float(snapshot.get("overall_score", 0.0)))

        self.assertEqual(len(response_rows), turn_count)
        for response_row in response_rows:
            self.assertTrue(response_row[0])
            self.assertTrue(response_row[1])
            self.assertTrue(response_row[2])
            self.assertGreaterEqual(float(response_row[3]), 0.0)
            self.assertLessEqual(float(response_row[3]), 100.0)

    def test_interview_orchestration_validation_and_not_found_contract(self) -> None:
        missing_status, missing_body = _request_json(
            self.base_url,
            "POST",
            f"{API_PREFIX}/interview-sessions/sess_missing_001/responses",
            body={"response": "Response for missing session."},
            headers={"Idempotency-Key": "contract-missing-session-001"},
        )
        self.assertEqual(missing_status, 404, missing_body)
        self.assertEqual(missing_body.get("error", {}).get("code"), "not_found")

        get_missing_status, get_missing_body = _request_json(
            self.base_url,
            "GET",
            f"{API_PREFIX}/interview-sessions/sess_missing_001",
        )
        self.assertEqual(get_missing_status, 404, get_missing_body)
        self.assertEqual(get_missing_body.get("error", {}).get("code"), "not_found")

        job_spec_id = self._create_job_spec_entity_for_interview()
        candidate_id = self._create_candidate_entity_for_interview()
        create_status, create_body = _request_json(
            self.base_url,
            "POST",
            f"{API_PREFIX}/interview-sessions",
            body={"job_spec_id": job_spec_id, "candidate_id": candidate_id},
        )
        self.assertEqual(create_status, 201, create_body)
        session_id = create_body.get("data", {}).get("session_id")
        self.assertIsInstance(session_id, str)
        self.assertTrue(session_id)
        assert isinstance(session_id, str)

        missing_header_status, missing_header_body = _request_json(
            self.base_url,
            "POST",
            f"{API_PREFIX}/interview-sessions/{session_id}/responses",
            body={"response": "Answer without idempotency key."},
        )
        self.assertEqual(missing_header_status, 400, missing_header_body)
        self.assertEqual(missing_header_body.get("error", {}).get("code"), "invalid_request")

        invalid_body_status, invalid_body = _request_json(
            self.base_url,
            "POST",
            f"{API_PREFIX}/interview-sessions/{session_id}/responses",
            body={"response": ""},
            headers={"Idempotency-Key": "contract-invalid-body-001"},
        )
        self.assertEqual(invalid_body_status, 400, invalid_body)
        self.assertEqual(invalid_body.get("error", {}).get("code"), "invalid_request")

        invalid_question_status, invalid_question_body = _request_json(
            self.base_url,
            "POST",
            f"{API_PREFIX}/interview-sessions/{session_id}/responses",
            body={"question_id": "q_missing", "response": "This question id does not exist."},
            headers={"Idempotency-Key": "contract-invalid-question-001"},
        )
        self.assertEqual(invalid_question_status, 400, invalid_question_body)
        self.assertEqual(invalid_question_body.get("error", {}).get("code"), "invalid_request")

        invalid_override_status, invalid_override_body = _request_json(
            self.base_url,
            "POST",
            f"{API_PREFIX}/interview-sessions/{session_id}/responses",
            body={
                "response": "Answer with malformed override payload.",
                "override_followup": {
                    "reviewer_id": "",
                    "reason": "Needs override",
                    "competency": "skill.communication",
                    "difficulty": 9,
                },
            },
            headers={"Idempotency-Key": "contract-invalid-override-001"},
        )
        self.assertEqual(invalid_override_status, 400, invalid_override_body)
        self.assertEqual(invalid_override_body.get("error", {}).get("code"), "invalid_request")

    def test_interview_response_expected_version_conflict_contract(self) -> None:
        job_spec_id = self._create_job_spec_entity_for_interview()
        candidate_id = self._create_candidate_entity_for_interview()
        create_status, create_body = _request_json(
            self.base_url,
            "POST",
            f"{API_PREFIX}/interview-sessions",
            body={"job_spec_id": job_spec_id, "candidate_id": candidate_id},
        )
        self.assertEqual(create_status, 201, create_body)
        session_id = create_body.get("data", {}).get("session_id")
        self.assertIsInstance(session_id, str)
        self.assertTrue(session_id)
        assert isinstance(session_id, str)

        conflict_status, conflict_body = _request_json(
            self.base_url,
            "POST",
            f"{API_PREFIX}/interview-sessions/{session_id}/responses",
            body={
                "response": "I improved reliability and delivery outcomes.",
                "expected_version": 42,
            },
            headers={"Idempotency-Key": "contract-expected-version-conflict-001"},
        )
        self.assertEqual(conflict_status, 409, conflict_body)
        self.assertEqual(conflict_body.get("error", {}).get("code"), "version_conflict")
        reasons = [detail.get("reason", "") for detail in conflict_body.get("error", {}).get("details", [])]
        self.assertTrue(any("current version is 1" in reason for reason in reasons))

    def test_reviewer_override_followup_contract(self) -> None:
        job_spec_id = self._create_job_spec_entity_for_interview()
        candidate_id = self._create_candidate_entity_for_interview()
        create_status, create_body = _request_json(
            self.base_url,
            "POST",
            f"{API_PREFIX}/interview-sessions",
            body={"job_spec_id": job_spec_id, "candidate_id": candidate_id},
        )
        self.assertEqual(create_status, 201, create_body)
        session = create_body.get("data", {})
        session_id = session.get("session_id")
        self.assertIsInstance(session_id, str)
        self.assertTrue(session_id)
        assert isinstance(session_id, str)

        opening_questions = session.get("questions", [])
        self.assertGreaterEqual(len(opening_questions), 1)
        current_version = int(session.get("version", 1))
        override_key = "contract-reviewer-override-001"

        for idx, question in enumerate(opening_questions, start=1):
            body: dict = {
                "question_id": question.get("question_id"),
                "response": (
                    "I aligned cross-functional stakeholders and improved uptime by 19%."
                    if idx < len(opening_questions)
                    else "ok"
                ),
                "expected_version": current_version,
            }
            idempotency_key = f"contract-reviewer-override-seed-{idx}"
            if idx == len(opening_questions):
                body["override_followup"] = {
                    "reviewer_id": "rev_contract_001",
                    "reason": "Need to probe communication and collaboration depth.",
                    "competency": "skill.communication",
                    "difficulty": 4,
                }
                idempotency_key = override_key

            update_status, update_body = _request_json(
                self.base_url,
                "POST",
                f"{API_PREFIX}/interview-sessions/{session_id}/responses",
                body=body,
                headers={"Idempotency-Key": idempotency_key},
            )
            self.assertEqual(update_status, 200, update_body)
            session = update_body.get("data", {})
            current_version += 1
            self.assertEqual(int(session.get("version", 0)), current_version)

        followup = session.get("questions", [])[-1]
        self.assertEqual(followup.get("competency"), "skill.communication")
        metadata = followup.get("planner_metadata", {})
        self.assertEqual(metadata.get("selection_reason"), "reviewer_override")
        self.assertTrue(metadata.get("override_applied"))
        self.assertEqual(metadata.get("override_reviewer_id"), "rev_contract_001")

        with closing(sqlite3.connect(self.db_path)) as conn:
            row = conn.execute(
                """
                SELECT request_json
                FROM interview_session_responses
                WHERE session_id = ? AND idempotency_key = ?
                """,
                (session_id, override_key),
            ).fetchone()
        self.assertIsNotNone(row)
        assert row is not None
        request_json = json.loads(str(row[0]))
        self.assertEqual(request_json.get("override_followup", {}).get("reviewer_id"), "rev_contract_001")
        self.assertEqual(request_json.get("expected_version"), current_version - 1)

    def test_create_and_get_feedback_report_contract(self) -> None:
        session_id = self._create_interview_session_entity_for_feedback()
        idempotency_key = f"feedback-create-{uuid.uuid4()}"

        create_status, create_body = _request_json(
            self.base_url,
            "POST",
            f"{API_PREFIX}/feedback-reports",
            body={"session_id": session_id},
            headers={"Idempotency-Key": idempotency_key},
        )
        self.assertEqual(create_status, 201, create_body)
        feedback_data = create_body.get("data", {})
        feedback_report_id = feedback_data.get("feedback_report_id")
        self.assertIsInstance(feedback_report_id, str)
        self.assertTrue(feedback_report_id)
        assert isinstance(feedback_report_id, str)
        self.assertEqual(feedback_data.get("session_id"), session_id)
        self.assertIsInstance(feedback_data.get("top_gaps"), list)
        self.assertGreaterEqual(len(feedback_data.get("top_gaps", [])), 1)
        self.assertIsInstance(feedback_data.get("action_plan"), list)
        self.assertGreaterEqual(len(feedback_data.get("action_plan", [])), 1)
        self.assertIsInstance(feedback_data.get("overall_score"), (int, float))
        self.assertGreaterEqual(float(feedback_data.get("overall_score", 0.0)), 0.0)
        self.assertLessEqual(float(feedback_data.get("overall_score", 0.0)), 100.0)
        self.assertIsInstance(feedback_data.get("answer_rewrites"), list)
        self.assertGreaterEqual(len(feedback_data.get("answer_rewrites", [])), 1)
        self.assertIsInstance(feedback_data.get("action_plan"), list)
        self.assertEqual(len(feedback_data.get("action_plan", [])), 30)
        self.assertEqual(
            [entry.get("day") for entry in feedback_data.get("action_plan", [])],
            list(range(1, 31)),
        )
        self.assertEqual(feedback_data.get("version"), 1)
        self.assertIsNone(feedback_data.get("supersedes_feedback_report_id"))
        first_gap = feedback_data.get("top_gaps", [None])[0]
        self.assertIsInstance(first_gap, dict)
        assert isinstance(first_gap, dict)
        self.assertIn(first_gap.get("severity"), {"low", "medium", "high", "critical"})
        self.assertTrue(str(first_gap.get("root_cause", "")).strip())
        self.assertTrue(str(first_gap.get("evidence", "")).strip())

        get_status, get_body = _request_json(
            self.base_url,
            "GET",
            f"{API_PREFIX}/feedback-reports/{feedback_report_id}",
        )
        self.assertEqual(get_status, 200, get_body)
        self.assertEqual(get_body.get("data", {}).get("feedback_report_id"), feedback_report_id)
        self.assertEqual(get_body.get("data", {}).get("session_id"), session_id)
        self.assertEqual(get_body.get("data", {}).get("overall_score"), feedback_data.get("overall_score"))
        self.assertEqual(get_body.get("data", {}).get("top_gaps"), feedback_data.get("top_gaps"))
        self.assertEqual(get_body.get("data", {}).get("action_plan"), feedback_data.get("action_plan"))
        self.assertEqual(get_body.get("data", {}).get("answer_rewrites"), feedback_data.get("answer_rewrites"))
        self.assertEqual(get_body.get("data", {}).get("version"), 1)
        self.assertIsNone(get_body.get("data", {}).get("supersedes_feedback_report_id"))

        self._assert_feedback_report_row_persisted(
            feedback_report_id=feedback_report_id,
            session_id=session_id,
            idempotency_key=idempotency_key,
        )

    def test_feedback_report_idempotency_conflict_contract(self) -> None:
        first_session_id = self._create_interview_session_entity_for_feedback()
        second_session_id = self._create_interview_session_entity_for_feedback()
        shared_key = f"feedback-idempotency-{uuid.uuid4()}"

        first_status, first_body = _request_json(
            self.base_url,
            "POST",
            f"{API_PREFIX}/feedback-reports",
            body={"session_id": first_session_id},
            headers={"Idempotency-Key": shared_key},
        )
        self.assertEqual(first_status, 201, first_body)
        first_report_id = first_body.get("data", {}).get("feedback_report_id")
        self.assertIsInstance(first_report_id, str)
        self.assertTrue(first_report_id)
        assert isinstance(first_report_id, str)

        replay_status, replay_body = _request_json(
            self.base_url,
            "POST",
            f"{API_PREFIX}/feedback-reports",
            body={"session_id": first_session_id},
            headers={"Idempotency-Key": shared_key},
        )
        self.assertEqual(replay_status, 201, replay_body)
        self.assertEqual(replay_body.get("data", {}).get("feedback_report_id"), first_report_id)

        conflict_status, conflict_body = _request_json(
            self.base_url,
            "POST",
            f"{API_PREFIX}/feedback-reports",
            body={"session_id": second_session_id},
            headers={"Idempotency-Key": shared_key},
        )
        self.assertEqual(conflict_status, 409, conflict_body)
        self.assertEqual(conflict_body.get("error", {}).get("code"), "idempotency_key_conflict")

    def test_feedback_report_expected_version_conflict_contract(self) -> None:
        session_id = self._create_interview_session_entity_for_feedback()

        first_status, first_body = _request_json(
            self.base_url,
            "POST",
            f"{API_PREFIX}/feedback-reports",
            body={"session_id": session_id},
            headers={"Idempotency-Key": f"feedback-version-initial-{uuid.uuid4()}"},
        )
        self.assertEqual(first_status, 201, first_body)
        first_data = first_body.get("data", {})
        first_report_id = first_data.get("feedback_report_id")
        self.assertIsInstance(first_report_id, str)
        self.assertEqual(first_data.get("version"), 1)

        conflict_status, conflict_body = _request_json(
            self.base_url,
            "POST",
            f"{API_PREFIX}/feedback-reports",
            body={"session_id": session_id, "expected_version": 0},
            headers={"Idempotency-Key": f"feedback-version-conflict-{uuid.uuid4()}"},
        )
        self.assertEqual(conflict_status, 409, conflict_body)
        self.assertEqual(conflict_body.get("error", {}).get("code"), "version_conflict")
        details = conflict_body.get("error", {}).get("details", [])
        self.assertTrue(any("current version is 1" in str(item.get("reason", "")) for item in details))

        second_status, second_body = _request_json(
            self.base_url,
            "POST",
            f"{API_PREFIX}/feedback-reports",
            body={"session_id": session_id, "expected_version": 1},
            headers={"Idempotency-Key": f"feedback-version-next-{uuid.uuid4()}"},
        )
        self.assertEqual(second_status, 201, second_body)
        second_data = second_body.get("data", {})
        self.assertEqual(second_data.get("version"), 2)
        self.assertEqual(second_data.get("supersedes_feedback_report_id"), first_report_id)

    def test_feedback_report_validation_and_not_found_contract(self) -> None:
        session_id = self._create_interview_session_entity_for_feedback()

        missing_header_status, missing_header_body = _request_json(
            self.base_url,
            "POST",
            f"{API_PREFIX}/feedback-reports",
            body={"session_id": session_id},
        )
        self.assertEqual(missing_header_status, 400, missing_header_body)
        self.assertEqual(missing_header_body.get("error", {}).get("code"), "invalid_request")

        invalid_body_status, invalid_body = _request_json(
            self.base_url,
            "POST",
            f"{API_PREFIX}/feedback-reports",
            body={},
            headers={"Idempotency-Key": "feedback-invalid-body-001"},
        )
        self.assertEqual(invalid_body_status, 400, invalid_body)
        self.assertEqual(invalid_body.get("error", {}).get("code"), "invalid_request")

        missing_session_status, missing_session_body = _request_json(
            self.base_url,
            "POST",
            f"{API_PREFIX}/feedback-reports",
            body={"session_id": "sess_missing_feedback_001"},
            headers={"Idempotency-Key": "feedback-missing-session-001"},
        )
        self.assertEqual(missing_session_status, 404, missing_session_body)
        self.assertEqual(missing_session_body.get("error", {}).get("code"), "not_found")

        get_missing_status, get_missing_body = _request_json(
            self.base_url,
            "GET",
            f"{API_PREFIX}/feedback-reports/fb_missing_001",
        )
        self.assertEqual(get_missing_status, 404, get_missing_body)
        self.assertEqual(get_missing_body.get("error", {}).get("code"), "not_found")

    def test_create_and_get_negotiation_plan_contract(self) -> None:
        candidate_id = self._create_candidate_entity_for_interview()
        target_role = "Senior Backend Engineer"
        idempotency_key = f"negotiation-create-{uuid.uuid4()}"

        create_status, create_body = _request_json(
            self.base_url,
            "POST",
            f"{API_PREFIX}/negotiation-plans",
            body={
                "candidate_id": candidate_id,
                "target_role": target_role,
                "current_base_salary": 150000,
                "target_base_salary": 180000,
                "compensation_currency": "usd",
                "offer_deadline_date": "2026-03-10",
            },
            headers={"Idempotency-Key": idempotency_key},
        )
        self.assertEqual(create_status, 201, create_body)
        data = create_body.get("data", {})
        negotiation_plan_id = data.get("negotiation_plan_id")
        self.assertIsInstance(negotiation_plan_id, str)
        self.assertTrue(negotiation_plan_id)
        assert isinstance(negotiation_plan_id, str)
        self.assertEqual(data.get("candidate_id"), candidate_id)
        self.assertEqual(data.get("target_role"), target_role)
        self.assertEqual(data.get("version"), 1)
        self.assertIsNone(data.get("supersedes_negotiation_plan_id"))
        self.assertEqual(data.get("offer_deadline_date"), "2026-03-10")
        compensation_targets = data.get("compensation_targets")
        self.assertIsInstance(compensation_targets, dict)
        assert isinstance(compensation_targets, dict)
        self.assertEqual(compensation_targets.get("currency"), "USD")
        self.assertEqual(compensation_targets.get("current_base_salary"), 150000)
        self.assertEqual(compensation_targets.get("target_base_salary"), 180000)
        self.assertGreaterEqual(compensation_targets.get("anchor_base_salary", 0), 180000)
        self.assertGreaterEqual(compensation_targets.get("walk_away_base_salary", 0), 150000)
        self.assertIn("recommended_counter_base_salary", compensation_targets)
        self.assertIn("market_reference_base_salary", compensation_targets)
        self.assertIn("confidence", compensation_targets)
        self.assertGreaterEqual(float(compensation_targets.get("confidence", 0.0)), 0.5)
        self.assertLessEqual(float(compensation_targets.get("confidence", 0.0)), 1.0)
        self.assertIsInstance(data.get("leverage_signals"), list)
        self.assertGreaterEqual(len(data.get("leverage_signals", [])), 1)
        self.assertIsInstance(data.get("risk_signals"), list)
        self.assertGreaterEqual(len(data.get("risk_signals", [])), 1)
        self.assertIsInstance(data.get("evidence_links"), list)
        self.assertGreaterEqual(len(data.get("evidence_links", [])), 1)
        self.assertIsInstance(data.get("anchor_band"), dict)
        anchor_band = data.get("anchor_band", {})
        assert isinstance(anchor_band, dict)
        self.assertEqual(anchor_band.get("currency"), "USD")
        self.assertLessEqual(anchor_band.get("floor_base_salary", 0), anchor_band.get("target_base_salary", 0))
        self.assertLessEqual(anchor_band.get("target_base_salary", 0), anchor_band.get("ceiling_base_salary", 0))
        self.assertIsInstance(data.get("concession_ladder"), list)
        concession_ladder = data.get("concession_ladder", [])
        assert isinstance(concession_ladder, list)
        self.assertGreaterEqual(len(concession_ladder), 1)
        self.assertEqual([entry.get("step") for entry in concession_ladder], list(range(1, len(concession_ladder) + 1)))
        self.assertIsInstance(data.get("objection_playbook"), list)
        self.assertGreaterEqual(len(data.get("objection_playbook", [])), 1)
        follow_up_plan = data.get("follow_up_plan")
        self.assertIsInstance(follow_up_plan, dict)
        assert isinstance(follow_up_plan, dict)
        self.assertIsInstance(follow_up_plan.get("thank_you_note"), dict)
        self.assertIsInstance(follow_up_plan.get("recruiter_cadence"), list)
        self.assertGreaterEqual(len(follow_up_plan.get("recruiter_cadence", [])), 1)
        self.assertIsInstance(follow_up_plan.get("outcome_branches"), list)
        self.assertGreaterEqual(len(follow_up_plan.get("outcome_branches", [])), 1)
        self.assertIsInstance(data.get("talking_points"), list)
        self.assertGreaterEqual(len(data.get("talking_points", [])), 1)
        self.assertIsInstance(data.get("follow_up_actions"), list)
        self.assertGreaterEqual(len(data.get("follow_up_actions", [])), 1)
        follow_up_actions = data.get("follow_up_actions", [])
        assert isinstance(follow_up_actions, list)
        day_offsets = [int(item.get("day_offset", -1)) for item in follow_up_actions if isinstance(item, dict)]
        self.assertEqual(day_offsets, sorted(day_offsets))
        self.assertGreaterEqual(min(day_offsets), 0)
        self.assertLessEqual(max(day_offsets), 30)

        get_status, get_body = _request_json(
            self.base_url,
            "GET",
            f"{API_PREFIX}/negotiation-plans/{negotiation_plan_id}",
        )
        self.assertEqual(get_status, 200, get_body)
        self.assertEqual(get_body.get("data", {}).get("negotiation_plan_id"), negotiation_plan_id)
        self.assertEqual(get_body.get("data", {}).get("candidate_id"), candidate_id)
        self.assertEqual(get_body.get("data", {}).get("target_role"), target_role)
        self.assertEqual(get_body.get("data", {}).get("compensation_targets"), data.get("compensation_targets"))
        self.assertEqual(get_body.get("data", {}).get("leverage_signals"), data.get("leverage_signals"))
        self.assertEqual(get_body.get("data", {}).get("risk_signals"), data.get("risk_signals"))
        self.assertEqual(get_body.get("data", {}).get("evidence_links"), data.get("evidence_links"))
        self.assertEqual(get_body.get("data", {}).get("anchor_band"), data.get("anchor_band"))
        self.assertEqual(get_body.get("data", {}).get("concession_ladder"), data.get("concession_ladder"))
        self.assertEqual(get_body.get("data", {}).get("objection_playbook"), data.get("objection_playbook"))
        self.assertEqual(get_body.get("data", {}).get("follow_up_plan"), data.get("follow_up_plan"))
        self.assertEqual(get_body.get("data", {}).get("follow_up_actions"), data.get("follow_up_actions"))
        self.assertEqual(get_body.get("data", {}).get("version"), 1)
        self.assertIsNone(get_body.get("data", {}).get("supersedes_negotiation_plan_id"))

        self._assert_negotiation_plan_row_persisted(
            negotiation_plan_id=negotiation_plan_id,
            candidate_id=candidate_id,
            target_role=target_role,
            idempotency_key=idempotency_key,
        )

    def test_negotiation_context_signals_are_deterministic_for_fixed_history_contract(self) -> None:
        candidate_id = self._create_candidate_entity_for_interview()
        job_spec_id = self._create_job_spec_entity_for_interview()

        create_session_status, create_session_body = _request_json(
            self.base_url,
            "POST",
            f"{API_PREFIX}/interview-sessions",
            body={
                "job_spec_id": job_spec_id,
                "candidate_id": candidate_id,
                "mode": "mock_interview",
            },
        )
        self.assertEqual(create_session_status, 201, create_session_body)
        session_data = create_session_body.get("data", {})
        session_id = session_data.get("session_id")
        self.assertIsInstance(session_id, str)
        self.assertTrue(session_id)
        assert isinstance(session_id, str)

        questions = session_data.get("questions")
        self.assertIsInstance(questions, list)
        self.assertGreaterEqual(len(questions or []), 1)
        assert isinstance(questions, list)
        first_question = questions[0]
        response_status, response_body = _request_json(
            self.base_url,
            "POST",
            f"{API_PREFIX}/interview-sessions/{session_id}/responses",
            body={
                "question_id": first_question.get("question_id"),
                "response": "I improved API uptime to 99.95% and reduced Sev-1 incidents by 40%.",
            },
            headers={"Idempotency-Key": f"negotiation-context-response-{uuid.uuid4()}"},
        )
        self.assertEqual(response_status, 200, response_body)

        feedback_status, feedback_body = _request_json(
            self.base_url,
            "POST",
            f"{API_PREFIX}/feedback-reports",
            body={"session_id": session_id},
            headers={"Idempotency-Key": f"negotiation-context-feedback-{uuid.uuid4()}"},
        )
        self.assertEqual(feedback_status, 201, feedback_body)

        trajectory_status, trajectory_body = _request_json(
            self.base_url,
            "POST",
            f"{API_PREFIX}/trajectory-plans",
            body={"candidate_id": candidate_id, "target_role": "Senior Backend Engineer"},
            headers={"Idempotency-Key": f"negotiation-context-trajectory-{uuid.uuid4()}"},
        )
        self.assertEqual(trajectory_status, 201, trajectory_body)

        first_status, first_body = _request_json(
            self.base_url,
            "POST",
            f"{API_PREFIX}/negotiation-plans",
            body={
                "candidate_id": candidate_id,
                "target_role": "Senior Backend Engineer",
                "current_base_salary": 165000,
                "target_base_salary": 195000,
                "offer_deadline_date": "2026-03-20",
            },
            headers={"Idempotency-Key": f"negotiation-context-first-{uuid.uuid4()}"},
        )
        self.assertEqual(first_status, 201, first_body)
        first_plan = first_body.get("data", {})

        second_status, second_body = _request_json(
            self.base_url,
            "POST",
            f"{API_PREFIX}/negotiation-plans",
            body={
                "candidate_id": candidate_id,
                "target_role": "Senior Backend Engineer",
                "current_base_salary": 165000,
                "target_base_salary": 195000,
                "offer_deadline_date": "2026-03-20",
            },
            headers={"Idempotency-Key": f"negotiation-context-second-{uuid.uuid4()}"},
        )
        self.assertEqual(second_status, 201, second_body)
        second_plan = second_body.get("data", {})

        first_version = first_plan.get("version")
        second_version = second_plan.get("version")
        self.assertIsInstance(first_version, int)
        self.assertIsInstance(second_version, int)
        assert isinstance(first_version, int)
        assert isinstance(second_version, int)
        self.assertNotEqual(second_plan.get("negotiation_plan_id"), first_plan.get("negotiation_plan_id"))
        self.assertEqual(second_version, first_version + 1)
        self.assertEqual(second_plan.get("supersedes_negotiation_plan_id"), first_plan.get("negotiation_plan_id"))
        self.assertEqual(second_plan.get("compensation_targets"), first_plan.get("compensation_targets"))
        self.assertEqual(second_plan.get("leverage_signals"), first_plan.get("leverage_signals"))
        self.assertEqual(second_plan.get("risk_signals"), first_plan.get("risk_signals"))
        self.assertEqual(second_plan.get("evidence_links"), first_plan.get("evidence_links"))
        self.assertEqual(second_plan.get("anchor_band"), first_plan.get("anchor_band"))
        self.assertEqual(second_plan.get("concession_ladder"), first_plan.get("concession_ladder"))
        self.assertEqual(second_plan.get("objection_playbook"), first_plan.get("objection_playbook"))
        self.assertEqual(second_plan.get("follow_up_plan"), first_plan.get("follow_up_plan"))
        self.assertEqual(second_plan.get("follow_up_actions"), first_plan.get("follow_up_actions"))

    def test_negotiation_plan_validation_and_not_found_contract(self) -> None:
        candidate_id = self._create_candidate_entity_for_interview()

        missing_header_status, missing_header_body = _request_json(
            self.base_url,
            "POST",
            f"{API_PREFIX}/negotiation-plans",
            body={"candidate_id": candidate_id, "target_role": "Backend Engineer"},
        )
        self.assertEqual(missing_header_status, 400, missing_header_body)
        self.assertEqual(missing_header_body.get("error", {}).get("code"), "invalid_request")

        invalid_body_status, invalid_body = _request_json(
            self.base_url,
            "POST",
            f"{API_PREFIX}/negotiation-plans",
            body={},
            headers={"Idempotency-Key": "negotiation-invalid-body-001"},
        )
        self.assertEqual(invalid_body_status, 400, invalid_body)
        self.assertEqual(invalid_body.get("error", {}).get("code"), "invalid_request")

        invalid_salary_status, invalid_salary_body = _request_json(
            self.base_url,
            "POST",
            f"{API_PREFIX}/negotiation-plans",
            body={
                "candidate_id": candidate_id,
                "target_role": "Backend Engineer",
                "current_base_salary": 160000,
                "target_base_salary": 150000,
            },
            headers={"Idempotency-Key": "negotiation-invalid-salary-001"},
        )
        self.assertEqual(invalid_salary_status, 400, invalid_salary_body)
        self.assertEqual(invalid_salary_body.get("error", {}).get("code"), "invalid_request")

        invalid_expected_status, invalid_expected_body = _request_json(
            self.base_url,
            "POST",
            f"{API_PREFIX}/negotiation-plans",
            body={
                "candidate_id": candidate_id,
                "target_role": "Backend Engineer",
                "expected_version": -1,
            },
            headers={"Idempotency-Key": "negotiation-invalid-expected-version-001"},
        )
        self.assertEqual(invalid_expected_status, 400, invalid_expected_body)
        self.assertEqual(invalid_expected_body.get("error", {}).get("code"), "invalid_request")

        invalid_regenerate_status, invalid_regenerate_body = _request_json(
            self.base_url,
            "POST",
            f"{API_PREFIX}/negotiation-plans",
            body={
                "candidate_id": candidate_id,
                "target_role": "Backend Engineer",
                "regenerate": "yes",
            },
            headers={"Idempotency-Key": "negotiation-invalid-regenerate-001"},
        )
        self.assertEqual(invalid_regenerate_status, 400, invalid_regenerate_body)
        self.assertEqual(invalid_regenerate_body.get("error", {}).get("code"), "invalid_request")

        first_status, first_body = _request_json(
            self.base_url,
            "POST",
            f"{API_PREFIX}/negotiation-plans",
            body={"candidate_id": candidate_id, "target_role": "Backend Engineer"},
            headers={"Idempotency-Key": "negotiation-contract-idempotency-001"},
        )
        self.assertEqual(first_status, 201, first_body)
        first_plan_id = first_body.get("data", {}).get("negotiation_plan_id")
        self.assertIsInstance(first_plan_id, str)
        self.assertTrue(first_plan_id)
        assert isinstance(first_plan_id, str)

        replay_status, replay_body = _request_json(
            self.base_url,
            "POST",
            f"{API_PREFIX}/negotiation-plans",
            body={"candidate_id": candidate_id, "target_role": "Backend Engineer"},
            headers={"Idempotency-Key": "negotiation-contract-idempotency-001"},
        )
        self.assertEqual(replay_status, 201, replay_body)
        self.assertEqual(replay_body.get("data", {}).get("negotiation_plan_id"), first_plan_id)

        conflict_status, conflict_body = _request_json(
            self.base_url,
            "POST",
            f"{API_PREFIX}/negotiation-plans",
            body={"candidate_id": candidate_id, "target_role": "Principal Backend Engineer"},
            headers={"Idempotency-Key": "negotiation-contract-idempotency-001"},
        )
        self.assertEqual(conflict_status, 409, conflict_body)
        self.assertEqual(conflict_body.get("error", {}).get("code"), "idempotency_key_conflict")

        missing_candidate_status, missing_candidate_body = _request_json(
            self.base_url,
            "POST",
            f"{API_PREFIX}/negotiation-plans",
            body={"candidate_id": "cand_missing_negotiation_001", "target_role": "Backend Engineer"},
            headers={"Idempotency-Key": "negotiation-missing-candidate-001"},
        )
        self.assertEqual(missing_candidate_status, 404, missing_candidate_body)
        self.assertEqual(missing_candidate_body.get("error", {}).get("code"), "not_found")

        get_missing_status, get_missing_body = _request_json(
            self.base_url,
            "GET",
            f"{API_PREFIX}/negotiation-plans/np_missing_001",
        )
        self.assertEqual(get_missing_status, 404, get_missing_body)
        self.assertEqual(get_missing_body.get("error", {}).get("code"), "not_found")

    def test_negotiation_plan_expected_version_conflict_and_regeneration_contract(self) -> None:
        candidate_id = self._create_candidate_entity_for_interview()
        target_role = "Staff Backend Engineer"

        first_status, first_body = _request_json(
            self.base_url,
            "POST",
            f"{API_PREFIX}/negotiation-plans",
            body={"candidate_id": candidate_id, "target_role": target_role},
            headers={"Idempotency-Key": f"negotiation-version-initial-{uuid.uuid4()}"},
        )
        self.assertEqual(first_status, 201, first_body)
        first_data = first_body.get("data", {})
        first_plan_id = first_data.get("negotiation_plan_id")
        self.assertIsInstance(first_plan_id, str)
        self.assertTrue(first_plan_id)
        assert isinstance(first_plan_id, str)
        self.assertEqual(first_data.get("version"), 1)
        self.assertIsNone(first_data.get("supersedes_negotiation_plan_id"))

        conflict_status, conflict_body = _request_json(
            self.base_url,
            "POST",
            f"{API_PREFIX}/negotiation-plans",
            body={
                "candidate_id": candidate_id,
                "target_role": target_role,
                "regenerate": True,
                "expected_version": 0,
            },
            headers={"Idempotency-Key": f"negotiation-version-conflict-{uuid.uuid4()}"},
        )
        self.assertEqual(conflict_status, 409, conflict_body)
        self.assertEqual(conflict_body.get("error", {}).get("code"), "version_conflict")
        conflict_details = conflict_body.get("error", {}).get("details", [])
        self.assertTrue(any("current version is 1" in str(item.get("reason", "")) for item in conflict_details))

        regenerate_key = f"negotiation-version-next-{uuid.uuid4()}"
        second_status, second_body = _request_json(
            self.base_url,
            "POST",
            f"{API_PREFIX}/negotiation-plans",
            body={
                "candidate_id": candidate_id,
                "target_role": target_role,
                "regenerate": True,
                "expected_version": 1,
            },
            headers={"Idempotency-Key": regenerate_key},
        )
        self.assertEqual(second_status, 201, second_body)
        second_data = second_body.get("data", {})
        second_plan_id = second_data.get("negotiation_plan_id")
        self.assertIsInstance(second_plan_id, str)
        self.assertTrue(second_plan_id)
        assert isinstance(second_plan_id, str)
        self.assertNotEqual(second_plan_id, first_plan_id)
        self.assertEqual(second_data.get("version"), 2)
        self.assertEqual(second_data.get("supersedes_negotiation_plan_id"), first_plan_id)

        regenerate_replay_status, regenerate_replay_body = _request_json(
            self.base_url,
            "POST",
            f"{API_PREFIX}/negotiation-plans",
            body={
                "candidate_id": candidate_id,
                "target_role": target_role,
                "regenerate": True,
                "expected_version": 1,
            },
            headers={"Idempotency-Key": regenerate_key},
        )
        self.assertEqual(regenerate_replay_status, 201, regenerate_replay_body)
        replay_data = regenerate_replay_body.get("data", {})
        self.assertEqual(replay_data.get("negotiation_plan_id"), second_plan_id)
        self.assertEqual(replay_data.get("version"), 2)
        self.assertEqual(replay_data.get("supersedes_negotiation_plan_id"), first_plan_id)

        stale_status, stale_body = _request_json(
            self.base_url,
            "POST",
            f"{API_PREFIX}/negotiation-plans",
            body={
                "candidate_id": candidate_id,
                "target_role": target_role,
                "regenerate": True,
                "expected_version": 1,
            },
            headers={"Idempotency-Key": f"negotiation-version-stale-{uuid.uuid4()}"},
        )
        self.assertEqual(stale_status, 409, stale_body)
        self.assertEqual(stale_body.get("error", {}).get("code"), "version_conflict")
        stale_details = stale_body.get("error", {}).get("details", [])
        self.assertTrue(any("current version is 2" in str(item.get("reason", "")) for item in stale_details))

        get_status, get_body = _request_json(
            self.base_url,
            "GET",
            f"{API_PREFIX}/negotiation-plans/{second_plan_id}",
        )
        self.assertEqual(get_status, 200, get_body)
        self.assertEqual(get_body.get("data", {}).get("version"), 2)
        self.assertEqual(get_body.get("data", {}).get("supersedes_negotiation_plan_id"), first_plan_id)

    def test_create_and_get_trajectory_plan_contract(self) -> None:
        candidate_id = self._create_candidate_entity_for_interview()
        target_role = "Senior Backend Engineer"
        idempotency_key = f"trajectory-create-{uuid.uuid4()}"

        create_status, create_body = _request_json(
            self.base_url,
            "POST",
            f"{API_PREFIX}/trajectory-plans",
            body={
                "candidate_id": candidate_id,
                "target_role": target_role,
            },
            headers={"Idempotency-Key": idempotency_key},
        )
        self.assertEqual(create_status, 201, create_body)
        data = create_body.get("data", {})
        trajectory_plan_id = data.get("trajectory_plan_id")
        self.assertIsInstance(trajectory_plan_id, str)
        self.assertTrue(trajectory_plan_id)
        assert isinstance(trajectory_plan_id, str)
        self.assertEqual(data.get("candidate_id"), candidate_id)
        self.assertEqual(data.get("target_role"), target_role)
        self.assertEqual(data.get("version"), 1)
        self.assertIsNone(data.get("supersedes_trajectory_plan_id"))
        self.assertIsInstance(data.get("milestones"), list)
        self.assertGreaterEqual(len(data.get("milestones", [])), 1)
        progress_summary = data.get("progress_summary")
        self.assertIsInstance(progress_summary, dict)
        assert isinstance(progress_summary, dict)
        history_counts = progress_summary.get("history_counts")
        self.assertIsInstance(history_counts, dict)
        assert isinstance(history_counts, dict)
        interview_count = history_counts.get("interview_sessions")
        feedback_count = history_counts.get("feedback_reports")
        snapshot_count = history_counts.get("snapshots")
        self.assertIsInstance(interview_count, int)
        self.assertIsInstance(feedback_count, int)
        self.assertIsInstance(snapshot_count, int)
        assert isinstance(interview_count, int)
        assert isinstance(feedback_count, int)
        assert isinstance(snapshot_count, int)
        self.assertGreaterEqual(interview_count, 0)
        self.assertGreaterEqual(feedback_count, 0)
        self.assertGreaterEqual(snapshot_count, 0)
        baseline = progress_summary.get("baseline")
        current = progress_summary.get("current")
        delta = progress_summary.get("delta")
        self.assertIsInstance(baseline, dict)
        self.assertIsInstance(current, dict)
        self.assertIsInstance(delta, dict)
        competency_trends = progress_summary.get("competency_trends")
        self.assertIsInstance(competency_trends, list)
        first_milestone = data.get("milestones", [None])[0]
        self.assertIsInstance(first_milestone, dict)
        assert isinstance(first_milestone, dict)
        self.assertTrue(str(first_milestone.get("name", "")).strip())
        self.assertTrue(str(first_milestone.get("target_date", "")).strip())
        self.assertTrue(str(first_milestone.get("metric", "")).strip())

        get_status, get_body = _request_json(
            self.base_url,
            "GET",
            f"{API_PREFIX}/trajectory-plans/{trajectory_plan_id}",
        )
        self.assertEqual(get_status, 200, get_body)
        self.assertEqual(get_body.get("data", {}).get("trajectory_plan_id"), trajectory_plan_id)
        self.assertEqual(get_body.get("data", {}).get("candidate_id"), candidate_id)
        self.assertEqual(get_body.get("data", {}).get("target_role"), target_role)
        self.assertEqual(get_body.get("data", {}).get("milestones"), data.get("milestones"))
        self.assertEqual(get_body.get("data", {}).get("weekly_plan"), data.get("weekly_plan"))
        self.assertEqual(get_body.get("data", {}).get("progress_summary"), data.get("progress_summary"))
        self.assertEqual(get_body.get("data", {}).get("version"), 1)
        self.assertIsNone(get_body.get("data", {}).get("supersedes_trajectory_plan_id"))

        self._assert_trajectory_plan_row_persisted(
            trajectory_plan_id=trajectory_plan_id,
            candidate_id=candidate_id,
            target_role=target_role,
            idempotency_key=idempotency_key,
        )

    def test_trajectory_plan_generation_is_date_ordered_and_evidence_linked_contract(self) -> None:
        candidate_id = self._create_candidate_entity_for_interview()
        job_spec_id = self._create_job_spec_entity_for_interview()

        create_session_status, create_session_body = _request_json(
            self.base_url,
            "POST",
            f"{API_PREFIX}/interview-sessions",
            body={
                "job_spec_id": job_spec_id,
                "candidate_id": candidate_id,
                "mode": "mock_interview",
            },
        )
        self.assertEqual(create_session_status, 201, create_session_body)
        session_data = create_session_body.get("data", {})
        session_id = session_data.get("session_id")
        self.assertIsInstance(session_id, str)
        self.assertTrue(session_id)
        assert isinstance(session_id, str)
        questions = session_data.get("questions", [])
        self.assertIsInstance(questions, list)
        self.assertGreaterEqual(len(questions), 1)
        first_question = questions[0]
        self.assertIsInstance(first_question, dict)
        assert isinstance(first_question, dict)

        respond_status, respond_body = _request_json(
            self.base_url,
            "POST",
            f"{API_PREFIX}/interview-sessions/{session_id}/responses",
            body={
                "question_id": first_question.get("question_id"),
                "response": "I collaborated on an API migration and improved reliability.",
            },
            headers={"Idempotency-Key": f"trajectory-evidence-response-{uuid.uuid4()}"},
        )
        self.assertEqual(respond_status, 200, respond_body)

        feedback_status, feedback_body = _request_json(
            self.base_url,
            "POST",
            f"{API_PREFIX}/feedback-reports",
            body={"session_id": session_id},
            headers={"Idempotency-Key": f"trajectory-evidence-feedback-{uuid.uuid4()}"},
        )
        self.assertEqual(feedback_status, 201, feedback_body)

        first_create_status, first_create_body = _request_json(
            self.base_url,
            "POST",
            f"{API_PREFIX}/trajectory-plans",
            body={"candidate_id": candidate_id, "target_role": "Senior Backend Engineer"},
            headers={"Idempotency-Key": f"trajectory-evidence-create-{uuid.uuid4()}"},
        )
        self.assertEqual(first_create_status, 201, first_create_body)
        first_plan = first_create_body.get("data", {})

        second_create_status, second_create_body = _request_json(
            self.base_url,
            "POST",
            f"{API_PREFIX}/trajectory-plans",
            body={"candidate_id": candidate_id, "target_role": "Senior Backend Engineer"},
            headers={"Idempotency-Key": f"trajectory-evidence-create-{uuid.uuid4()}"},
        )
        self.assertEqual(second_create_status, 201, second_create_body)
        second_plan = second_create_body.get("data", {})
        first_version = first_plan.get("version")
        second_version = second_plan.get("version")
        self.assertIsInstance(first_version, int)
        self.assertIsInstance(second_version, int)
        assert isinstance(first_version, int)
        assert isinstance(second_version, int)
        self.assertEqual(second_version, first_version + 1)
        self.assertNotEqual(second_plan.get("trajectory_plan_id"), first_plan.get("trajectory_plan_id"))
        self.assertEqual(second_plan.get("supersedes_trajectory_plan_id"), first_plan.get("trajectory_plan_id"))
        self.assertEqual(second_plan.get("milestones"), first_plan.get("milestones"))
        self.assertEqual(second_plan.get("weekly_plan"), first_plan.get("weekly_plan"))

        milestones = first_plan.get("milestones")
        self.assertIsInstance(milestones, list)
        assert isinstance(milestones, list)
        self.assertGreaterEqual(len(milestones), 3)
        milestone_dates = [str(item.get("target_date", "")) for item in milestones if isinstance(item, dict)]
        self.assertEqual(milestone_dates, sorted(milestone_dates))

        weekly_plan = first_plan.get("weekly_plan")
        self.assertIsInstance(weekly_plan, list)
        assert isinstance(weekly_plan, list)
        self.assertGreaterEqual(len(weekly_plan), 4)
        self.assertLessEqual(len(weekly_plan), 8)
        self.assertEqual([entry.get("week") for entry in weekly_plan], list(range(1, len(weekly_plan) + 1)))
        first_week_actions = " ".join(str(action) for action in weekly_plan[0].get("actions", [])).lower()
        self.assertIn("current=", first_week_actions)
        self.assertIn("target=", first_week_actions)
        self.assertIn("delta=", first_week_actions)

        progress_summary = first_plan.get("progress_summary", {})
        self.assertIsInstance(progress_summary, dict)
        top_risk = progress_summary.get("top_risk_competencies", [])
        if isinstance(top_risk, list) and top_risk:
            expected_label = str(top_risk[0]).replace("skill.", "").replace("_", " ").lower()
            self.assertIn(expected_label, first_week_actions)

    def test_trajectory_plan_idempotency_conflict_contract(self) -> None:
        candidate_id = self._create_candidate_entity_for_interview()
        shared_key = f"trajectory-idempotency-{uuid.uuid4()}"

        first_status, first_body = _request_json(
            self.base_url,
            "POST",
            f"{API_PREFIX}/trajectory-plans",
            body={
                "candidate_id": candidate_id,
                "target_role": "Staff Backend Engineer",
            },
            headers={"Idempotency-Key": shared_key},
        )
        self.assertEqual(first_status, 201, first_body)
        first_plan_id = first_body.get("data", {}).get("trajectory_plan_id")
        self.assertIsInstance(first_plan_id, str)
        self.assertTrue(first_plan_id)
        assert isinstance(first_plan_id, str)

        replay_status, replay_body = _request_json(
            self.base_url,
            "POST",
            f"{API_PREFIX}/trajectory-plans",
            body={
                "candidate_id": candidate_id,
                "target_role": "Staff Backend Engineer",
            },
            headers={"Idempotency-Key": shared_key},
        )
        self.assertEqual(replay_status, 201, replay_body)
        self.assertEqual(replay_body.get("data", {}).get("trajectory_plan_id"), first_plan_id)

        conflict_status, conflict_body = _request_json(
            self.base_url,
            "POST",
            f"{API_PREFIX}/trajectory-plans",
            body={
                "candidate_id": candidate_id,
                "target_role": "Principal Backend Engineer",
            },
            headers={"Idempotency-Key": shared_key},
        )
        self.assertEqual(conflict_status, 409, conflict_body)
        self.assertEqual(conflict_body.get("error", {}).get("code"), "idempotency_key_conflict")

    def test_trajectory_plan_expected_version_conflict_and_regeneration_contract(self) -> None:
        candidate_id = self._create_candidate_entity_for_interview()
        target_role = "Staff Backend Engineer"

        first_status, first_body = _request_json(
            self.base_url,
            "POST",
            f"{API_PREFIX}/trajectory-plans",
            body={"candidate_id": candidate_id, "target_role": target_role},
            headers={"Idempotency-Key": f"trajectory-version-initial-{uuid.uuid4()}"},
        )
        self.assertEqual(first_status, 201, first_body)
        first_data = first_body.get("data", {})
        first_plan_id = first_data.get("trajectory_plan_id")
        self.assertIsInstance(first_plan_id, str)
        self.assertTrue(first_plan_id)
        assert isinstance(first_plan_id, str)
        self.assertEqual(first_data.get("version"), 1)
        self.assertIsNone(first_data.get("supersedes_trajectory_plan_id"))

        conflict_status, conflict_body = _request_json(
            self.base_url,
            "POST",
            f"{API_PREFIX}/trajectory-plans",
            body={
                "candidate_id": candidate_id,
                "target_role": target_role,
                "regenerate": True,
                "expected_version": 0,
            },
            headers={"Idempotency-Key": f"trajectory-version-conflict-{uuid.uuid4()}"},
        )
        self.assertEqual(conflict_status, 409, conflict_body)
        self.assertEqual(conflict_body.get("error", {}).get("code"), "version_conflict")
        conflict_details = conflict_body.get("error", {}).get("details", [])
        self.assertTrue(any("current version is 1" in str(item.get("reason", "")) for item in conflict_details))

        regenerate_key = f"trajectory-version-next-{uuid.uuid4()}"
        second_status, second_body = _request_json(
            self.base_url,
            "POST",
            f"{API_PREFIX}/trajectory-plans",
            body={
                "candidate_id": candidate_id,
                "target_role": target_role,
                "regenerate": True,
                "expected_version": 1,
            },
            headers={"Idempotency-Key": regenerate_key},
        )
        self.assertEqual(second_status, 201, second_body)
        second_data = second_body.get("data", {})
        second_plan_id = second_data.get("trajectory_plan_id")
        self.assertIsInstance(second_plan_id, str)
        self.assertTrue(second_plan_id)
        assert isinstance(second_plan_id, str)
        self.assertNotEqual(second_plan_id, first_plan_id)
        self.assertEqual(second_data.get("version"), 2)
        self.assertEqual(second_data.get("supersedes_trajectory_plan_id"), first_plan_id)

        regenerate_replay_status, regenerate_replay_body = _request_json(
            self.base_url,
            "POST",
            f"{API_PREFIX}/trajectory-plans",
            body={
                "candidate_id": candidate_id,
                "target_role": target_role,
                "regenerate": True,
                "expected_version": 1,
            },
            headers={"Idempotency-Key": regenerate_key},
        )
        self.assertEqual(regenerate_replay_status, 201, regenerate_replay_body)
        replay_data = regenerate_replay_body.get("data", {})
        self.assertEqual(replay_data.get("trajectory_plan_id"), second_plan_id)
        self.assertEqual(replay_data.get("version"), 2)
        self.assertEqual(replay_data.get("supersedes_trajectory_plan_id"), first_plan_id)

        stale_status, stale_body = _request_json(
            self.base_url,
            "POST",
            f"{API_PREFIX}/trajectory-plans",
            body={
                "candidate_id": candidate_id,
                "target_role": target_role,
                "regenerate": True,
                "expected_version": 1,
            },
            headers={"Idempotency-Key": f"trajectory-version-stale-{uuid.uuid4()}"},
        )
        self.assertEqual(stale_status, 409, stale_body)
        self.assertEqual(stale_body.get("error", {}).get("code"), "version_conflict")
        stale_details = stale_body.get("error", {}).get("details", [])
        self.assertTrue(any("current version is 2" in str(item.get("reason", "")) for item in stale_details))

    def test_trajectory_plan_validation_and_not_found_contract(self) -> None:
        candidate_id = self._create_candidate_entity_for_interview()

        missing_header_status, missing_header_body = _request_json(
            self.base_url,
            "POST",
            f"{API_PREFIX}/trajectory-plans",
            body={
                "candidate_id": candidate_id,
                "target_role": "Backend Engineer",
            },
        )
        self.assertEqual(missing_header_status, 400, missing_header_body)
        self.assertEqual(missing_header_body.get("error", {}).get("code"), "invalid_request")

        invalid_body_status, invalid_body = _request_json(
            self.base_url,
            "POST",
            f"{API_PREFIX}/trajectory-plans",
            body={},
            headers={"Idempotency-Key": "trajectory-invalid-body-001"},
        )
        self.assertEqual(invalid_body_status, 400, invalid_body)
        self.assertEqual(invalid_body.get("error", {}).get("code"), "invalid_request")

        invalid_expected_status, invalid_expected_body = _request_json(
            self.base_url,
            "POST",
            f"{API_PREFIX}/trajectory-plans",
            body={
                "candidate_id": candidate_id,
                "target_role": "Backend Engineer",
                "expected_version": -1,
            },
            headers={"Idempotency-Key": "trajectory-invalid-expected-version-001"},
        )
        self.assertEqual(invalid_expected_status, 400, invalid_expected_body)
        self.assertEqual(invalid_expected_body.get("error", {}).get("code"), "invalid_request")

        invalid_regenerate_status, invalid_regenerate_body = _request_json(
            self.base_url,
            "POST",
            f"{API_PREFIX}/trajectory-plans",
            body={
                "candidate_id": candidate_id,
                "target_role": "Backend Engineer",
                "regenerate": "yes",
            },
            headers={"Idempotency-Key": "trajectory-invalid-regenerate-001"},
        )
        self.assertEqual(invalid_regenerate_status, 400, invalid_regenerate_body)
        self.assertEqual(invalid_regenerate_body.get("error", {}).get("code"), "invalid_request")

        missing_candidate_status, missing_candidate_body = _request_json(
            self.base_url,
            "POST",
            f"{API_PREFIX}/trajectory-plans",
            body={
                "candidate_id": "cand_missing_trajectory_001",
                "target_role": "Backend Engineer",
            },
            headers={"Idempotency-Key": "trajectory-missing-candidate-001"},
        )
        self.assertEqual(missing_candidate_status, 404, missing_candidate_body)
        self.assertEqual(missing_candidate_body.get("error", {}).get("code"), "not_found")

        get_missing_status, get_missing_body = _request_json(
            self.base_url,
            "GET",
            f"{API_PREFIX}/trajectory-plans/tp_missing_001",
        )
        self.assertEqual(get_missing_status, 404, get_missing_body)
        self.assertEqual(get_missing_body.get("error", {}).get("code"), "not_found")

    def test_get_candidate_progress_dashboard_contract(self) -> None:
        candidate_source_id = f"cand_contract_dashboard_{uuid.uuid4().hex[:8]}"
        candidate_create_status, candidate_create_body = _request_json(
            self.base_url,
            "POST",
            f"{API_PREFIX}/candidate-ingestions",
            body={
                "candidate_id": candidate_source_id,
                "cv_text": (
                    "Jordan Lane\n"
                    "Senior Backend Engineer\n"
                    "Built reliable API workflows with Python and SQL.\n"
                ),
                "target_roles": ["Senior Backend Engineer"],
            },
            headers={"Idempotency-Key": f"candidate-dashboard-{uuid.uuid4()}"},
        )
        self.assertEqual(candidate_create_status, 202, candidate_create_body)
        candidate_ingestion_id = self._assert_ingestion_accepted_response(candidate_create_body)

        candidate_get_status, candidate_get_body = self._wait_for_candidate_ingestion_status(candidate_ingestion_id)
        self.assertEqual(candidate_get_status, 200, candidate_get_body)
        candidate_result = candidate_get_body.get("data", {}).get("result", {})
        candidate_id = candidate_result.get("entity_id") if isinstance(candidate_result, dict) else None
        self.assertIsInstance(candidate_id, str)
        self.assertTrue(candidate_id)
        assert isinstance(candidate_id, str)

        job_spec_id = self._create_job_spec_entity_for_interview()

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
                        "sess_contract_dash_001",
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
                        "sess_contract_dash_002",
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
                        "feedback_report_id": "fb_contract_dash_001",
                        "session_id": "sess_contract_dash_002",
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
                        "fb_contract_dash_001",
                        "sess_contract_dash_002",
                        "feedback-contract-dash-001",
                        "{}",
                        feedback_payload,
                        "2026-02-24T10:00:00Z",
                        "2026-02-24T10:00:00Z",
                        1,
                        None,
                    ),
                )

        first_plan_status, first_plan_body = _request_json(
            self.base_url,
            "POST",
            f"{API_PREFIX}/trajectory-plans",
            body={
                "candidate_id": candidate_id,
                "target_role": "Senior Backend Engineer",
            },
            headers={"Idempotency-Key": f"dashboard-trajectory-initial-{uuid.uuid4()}"},
        )
        self.assertEqual(first_plan_status, 201, first_plan_body)
        first_plan_id = first_plan_body.get("data", {}).get("trajectory_plan_id")
        self.assertIsInstance(first_plan_id, str)
        self.assertTrue(first_plan_id)
        assert isinstance(first_plan_id, str)

        second_plan_status, second_plan_body = _request_json(
            self.base_url,
            "POST",
            f"{API_PREFIX}/trajectory-plans",
            body={
                "candidate_id": candidate_id,
                "target_role": "Senior Backend Engineer",
                "regenerate": True,
                "expected_version": 1,
            },
            headers={"Idempotency-Key": f"dashboard-trajectory-next-{uuid.uuid4()}"},
        )
        self.assertEqual(second_plan_status, 201, second_plan_body)
        second_plan_id = second_plan_body.get("data", {}).get("trajectory_plan_id")
        self.assertIsInstance(second_plan_id, str)
        self.assertTrue(second_plan_id)
        assert isinstance(second_plan_id, str)

        encoded_target_role = parse.quote("Senior Backend Engineer")
        dashboard_status, dashboard_body = _request_json(
            self.base_url,
            "GET",
            f"{API_PREFIX}/candidates/{candidate_id}/progress-dashboard?target_role={encoded_target_role}",
        )
        self.assertEqual(dashboard_status, 200, dashboard_body)
        dashboard_data = dashboard_body.get("data", {})
        self.assertEqual(dashboard_data.get("candidate_id"), candidate_id)

        second_dashboard_status, second_dashboard_body = _request_json(
            self.base_url,
            "GET",
            f"{API_PREFIX}/candidates/{candidate_id}/progress-dashboard?target_role={encoded_target_role}",
        )
        self.assertEqual(second_dashboard_status, 200, second_dashboard_body)
        self.assertEqual(second_dashboard_body.get("data"), dashboard_data)

        top_improving = dashboard_data.get("competency_trend_cards", {}).get("top_improving", [])
        self.assertEqual([entry.get("competency") for entry in top_improving], ["skill.communication", "skill.python"])

        top_risk = dashboard_data.get("competency_trend_cards", {}).get("top_risk", [])
        self.assertEqual(
            [entry.get("competency") for entry in top_risk],
            ["skill.execution", "skill.communication", "skill.python"],
        )

        readiness = dashboard_data.get("readiness_signals", {})
        self.assertEqual(readiness.get("snapshot_count"), 3)
        self.assertEqual(readiness.get("momentum"), "improving")
        self.assertIn(readiness.get("readiness_band"), {"developing", "strong"})

        latest_trajectory = dashboard_data.get("latest_trajectory_plan", {})
        self.assertTrue(latest_trajectory.get("available"))
        self.assertEqual(latest_trajectory.get("trajectory_plan_id"), second_plan_id)
        self.assertEqual(latest_trajectory.get("version"), 2)
        self.assertEqual(latest_trajectory.get("supersedes_trajectory_plan_id"), first_plan_id)
        self.assertEqual(latest_trajectory.get("target_role"), "Senior Backend Engineer")

    def test_candidate_progress_dashboard_empty_history_and_validation_contract(self) -> None:
        candidate_source_id = f"cand_contract_dashboard_empty_{uuid.uuid4().hex[:8]}"
        candidate_create_status, candidate_create_body = _request_json(
            self.base_url,
            "POST",
            f"{API_PREFIX}/candidate-ingestions",
            body={
                "candidate_id": candidate_source_id,
                "cv_text": "Dashboard empty-history candidate profile.",
                "target_roles": ["Backend Engineer"],
            },
            headers={"Idempotency-Key": f"candidate-dashboard-empty-{uuid.uuid4()}"},
        )
        self.assertEqual(candidate_create_status, 202, candidate_create_body)
        candidate_ingestion_id = self._assert_ingestion_accepted_response(candidate_create_body)

        candidate_get_status, candidate_get_body = self._wait_for_candidate_ingestion_status(candidate_ingestion_id)
        self.assertEqual(candidate_get_status, 200, candidate_get_body)
        candidate_result = candidate_get_body.get("data", {}).get("result", {})
        candidate_id = candidate_result.get("entity_id") if isinstance(candidate_result, dict) else None
        self.assertIsInstance(candidate_id, str)
        self.assertTrue(candidate_id)
        assert isinstance(candidate_id, str)

        dashboard_status, dashboard_body = _request_json(
            self.base_url,
            "GET",
            f"{API_PREFIX}/candidates/{candidate_id}/progress-dashboard",
        )
        self.assertEqual(dashboard_status, 200, dashboard_body)
        dashboard_data = dashboard_body.get("data", {})
        self.assertEqual(dashboard_data.get("candidate_id"), candidate_id)
        self.assertEqual(dashboard_data.get("progress_summary", {}).get("history_counts", {}).get("snapshots"), 0)
        self.assertEqual(dashboard_data.get("competency_trend_cards", {}).get("top_improving"), [])
        self.assertEqual(dashboard_data.get("competency_trend_cards", {}).get("top_risk"), [])
        self.assertEqual(dashboard_data.get("readiness_signals", {}).get("snapshot_count"), 0)
        self.assertEqual(dashboard_data.get("readiness_signals", {}).get("readiness_band"), "insufficient_data")
        self.assertEqual(dashboard_data.get("readiness_signals", {}).get("momentum"), "unknown")
        self.assertFalse(dashboard_data.get("latest_trajectory_plan", {}).get("available"))

        invalid_query_status, invalid_query_body = _request_json(
            self.base_url,
            "GET",
            f"{API_PREFIX}/candidates/{candidate_id}/progress-dashboard?target_role=",
        )
        self.assertEqual(invalid_query_status, 400, invalid_query_body)
        self.assertEqual(invalid_query_body.get("error", {}).get("code"), "invalid_request")

        missing_status, missing_body = _request_json(
            self.base_url,
            "GET",
            f"{API_PREFIX}/candidates/cand_contract_dashboard_missing_{uuid.uuid4().hex[:8]}/progress-dashboard",
        )
        self.assertEqual(missing_status, 404, missing_body)
        self.assertEqual(missing_body.get("error", {}).get("code"), "not_found")

    def _create_interview_session_entity_for_feedback(self) -> str:
        job_spec_id = self._create_job_spec_entity_for_interview()
        candidate_id = self._create_candidate_entity_for_interview()
        create_status, create_body = _request_json(
            self.base_url,
            "POST",
            f"{API_PREFIX}/interview-sessions",
            body={
                "job_spec_id": job_spec_id,
                "candidate_id": candidate_id,
                "mode": "mock_interview",
            },
        )
        self.assertEqual(create_status, 201, create_body)

        session_data = create_body.get("data", {})
        session_id = session_data.get("session_id")
        self.assertIsInstance(session_id, str)
        self.assertTrue(session_id)
        assert isinstance(session_id, str)
        return session_id

    def _create_job_spec_entity_for_interview(self) -> str:
        create_payload = {
            "source_type": "text",
            "source_value": (
                "Backend Engineer\n"
                "Responsibilities:\n"
                "- Build Python services.\n"
                "Requirements:\n"
                "- Strong SQL.\n"
                "Preferred Qualifications:\n"
                "- API design.\n"
            ),
        }
        idempotency_key = f"interview-job-{uuid.uuid4()}"
        create_status, create_body = _request_json(
            self.base_url,
            "POST",
            f"{API_PREFIX}/job-ingestions",
            body=create_payload,
            headers={"Idempotency-Key": idempotency_key},
        )
        self.assertEqual(create_status, 202, create_body)
        ingestion_id = self._assert_ingestion_accepted_response(create_body)

        get_status, get_body = self._wait_for_ingestion_status(ingestion_id)
        self.assertEqual(get_status, 200, get_body)
        data = get_body.get("data", {})
        result = data.get("result", {}) if isinstance(data, dict) else {}
        job_spec_id = result.get("entity_id") if isinstance(result, dict) else None
        self.assertIsInstance(job_spec_id, str)
        self.assertTrue(job_spec_id)
        assert isinstance(job_spec_id, str)
        return job_spec_id

    def _create_candidate_entity_for_interview(self) -> str:
        payload = {
            "candidate_id": "cand_contract_interview_001",
            "cv_text": (
                "Alex Kim\n"
                "Staff Engineer\n"
                "Acme Corp | Senior Engineer | 2020-01 - Present\n"
                "Built reliable APIs in Python and SQL.\n"
            ),
            "story_notes": ["Reduced latency by 35% and improved deployment success rate to 98%."],
            "target_roles": ["Staff Engineer"],
        }
        idempotency_key = f"interview-candidate-{uuid.uuid4()}"
        create_status, create_body = _request_json(
            self.base_url,
            "POST",
            f"{API_PREFIX}/candidate-ingestions",
            body=payload,
            headers={"Idempotency-Key": idempotency_key},
        )
        self.assertEqual(create_status, 202, create_body)
        ingestion_id = self._assert_ingestion_accepted_response(create_body)

        get_status, get_body = self._wait_for_candidate_ingestion_status(ingestion_id)
        self.assertEqual(get_status, 200, get_body)
        data = get_body.get("data", {})
        result = data.get("result", {}) if isinstance(data, dict) else {}
        candidate_id = result.get("entity_id") if isinstance(result, dict) else None
        self.assertIsInstance(candidate_id, str)
        self.assertTrue(candidate_id)
        assert isinstance(candidate_id, str)
        return candidate_id

    def _wait_for_ingestion_status(self, ingestion_id: str) -> tuple[int, dict]:
        deadline = time.monotonic() + REQUEST_TIMEOUT_SECONDS
        last_status = 0
        last_body: dict = {}
        while time.monotonic() < deadline:
            status, body = _request_json(
                self.base_url, "GET", f"{API_PREFIX}/job-ingestions/{ingestion_id}"
            )
            last_status, last_body = status, body
            if status == 200:
                return status, body
            time.sleep(0.1)
        return last_status, last_body

    def _wait_for_candidate_ingestion_status(self, ingestion_id: str) -> tuple[int, dict]:
        deadline = time.monotonic() + REQUEST_TIMEOUT_SECONDS
        last_status = 0
        last_body: dict = {}
        while time.monotonic() < deadline:
            status, body = _request_json(
                self.base_url, "GET", f"{API_PREFIX}/candidate-ingestions/{ingestion_id}"
            )
            last_status, last_body = status, body
            if status == 200:
                return status, body
            time.sleep(0.1)
        return last_status, last_body

    def _assert_ingestion_row_persisted(
        self, ingestion_id: str, payload: dict, idempotency_key: str
    ) -> None:
        deadline = time.monotonic() + REQUEST_TIMEOUT_SECONDS
        row = None
        while time.monotonic() < deadline:
            with closing(sqlite3.connect(self.db_path)) as conn:
                row = conn.execute(
                    """
                    SELECT ingestion_id, idempotency_key, source_type, source_value, status
                    FROM job_ingestions
                    WHERE ingestion_id = ?
                    """,
                    (ingestion_id,),
                ).fetchone()
            if row:
                break
            time.sleep(0.1)

        self.assertIsNotNone(
            row,
            (
                "POST response returned an ingestion_id that was not persisted into "
                f"the bootstrapped database at {self.db_path}."
            ),
        )
        assert row is not None
        self.assertEqual(row[0], ingestion_id)
        self.assertEqual(row[1], idempotency_key)
        self.assertEqual(row[2], payload["source_type"])
        self.assertEqual(row[3], payload["source_value"])
        self.assertEqual(row[4], "queued")

    def _assert_candidate_ingestion_row_persisted(
        self, ingestion_id: str, payload: dict, idempotency_key: str
    ) -> None:
        deadline = time.monotonic() + REQUEST_TIMEOUT_SECONDS
        row = None
        while time.monotonic() < deadline:
            with closing(sqlite3.connect(self.db_path)) as conn:
                row = conn.execute(
                    """
                    SELECT ingestion_id, idempotency_key, candidate_id, cv_text, cv_document_ref, story_notes_json, target_roles_json, status
                    FROM candidate_ingestions
                    WHERE ingestion_id = ?
                    """,
                    (ingestion_id,),
                ).fetchone()
            if row:
                break
            time.sleep(0.1)

        self.assertIsNotNone(
            row,
            (
                "POST response returned an ingestion_id that was not persisted into "
                f"the bootstrapped database at {self.db_path}."
            ),
        )
        assert row is not None
        self.assertEqual(row[0], ingestion_id)
        self.assertEqual(row[1], idempotency_key)
        self.assertEqual(row[2], payload["candidate_id"])
        self.assertEqual(row[3], payload.get("cv_text"))
        self.assertEqual(row[4], payload.get("cv_document_ref"))
        self.assertEqual(row[5], json.dumps(payload.get("story_notes"), separators=(",", ":")))
        self.assertEqual(row[6], json.dumps(payload.get("target_roles"), separators=(",", ":")))
        self.assertEqual(row[7], "queued")

    def _assert_candidate_profile_row_persisted(self, *, ingestion_id: str, candidate_id: str) -> None:
        deadline = time.monotonic() + REQUEST_TIMEOUT_SECONDS
        row = None
        while time.monotonic() < deadline:
            with closing(sqlite3.connect(self.db_path)) as conn:
                row = conn.execute(
                    """
                    SELECT candidate_id, ingestion_id, summary, experience_json, skills_json, parse_confidence, version
                    FROM candidate_profiles
                    WHERE candidate_id = ?
                    """,
                    (candidate_id,),
                ).fetchone()
            if row:
                break
            time.sleep(0.1)

        self.assertIsNotNone(
            row,
            (
                "Candidate profile row was not persisted for candidate ingestion "
                f"{ingestion_id} in database {self.db_path}."
            ),
        )
        assert row is not None
        self.assertEqual(row[0], candidate_id)
        self.assertEqual(row[1], ingestion_id)
        self.assertIsInstance(row[2], str)
        self.assertTrue(row[2])
        experience = json.loads(row[3])
        self.assertIsInstance(experience, list)
        self.assertGreater(len(experience), 0)
        skills = json.loads(row[4])
        self.assertIsInstance(skills, dict)
        self.assertGreater(len(skills), 0)
        self.assertGreaterEqual(float(row[5]), 0.0)
        self.assertLessEqual(float(row[5]), 1.0)
        self.assertGreaterEqual(int(row[6]), 1)

    def _assert_candidate_storybank_rows_persisted(self, *, candidate_id: str) -> None:
        deadline = time.monotonic() + REQUEST_TIMEOUT_SECONDS
        rows = []
        while time.monotonic() < deadline:
            with closing(sqlite3.connect(self.db_path)) as conn:
                rows = conn.execute(
                    """
                    SELECT story_id, situation, task, action, result, competencies_json, metrics_json, evidence_quality
                    FROM candidate_storybank
                    WHERE candidate_id = ?
                    ORDER BY created_at ASC, story_id ASC
                    """,
                    (candidate_id,),
                ).fetchall()
            if rows:
                break
            time.sleep(0.1)

        self.assertGreaterEqual(len(rows), 1, f"No candidate_storybank rows persisted for candidate_id={candidate_id}")
        for row in rows:
            self.assertTrue(row[0])
            self.assertTrue(row[1])
            self.assertTrue(row[2])
            self.assertTrue(row[3])
            self.assertTrue(row[4])
            competencies = json.loads(row[5])
            self.assertIsInstance(competencies, list)
            self.assertGreaterEqual(len(competencies), 1)
            if row[6] is not None:
                metrics = json.loads(row[6])
                self.assertIsInstance(metrics, list)
            self.assertGreaterEqual(float(row[7]), 0.0)
        self.assertLessEqual(float(row[7]), 1.0)

    def _assert_taxonomy_mapping_rows_persisted(
        self,
        *,
        expected: dict[str, tuple[str | None, float]],
    ) -> None:
        with closing(sqlite3.connect(self.db_path)) as conn:
            rows = conn.execute(
                """
                SELECT input_term, canonical_term, confidence
                FROM taxonomy_mappings
                WHERE taxonomy_version = ?
                ORDER BY input_term ASC
                """,
                ("m1-taxonomy-v1",),
            ).fetchall()

        row_map = {str(row[0]): (str(row[1]), float(row[2])) for row in rows}
        for input_term, (canonical_term, confidence) in expected.items():
            self.assertIn(input_term, row_map)
            actual_canonical, actual_confidence = row_map[input_term]
            if canonical_term is None:
                self.assertTrue(actual_canonical.startswith("skill.freeform."))
            else:
                self.assertEqual(actual_canonical, canonical_term)
            self.assertAlmostEqual(actual_confidence, confidence, places=6)

    def _assert_eval_run_row_persisted(
        self,
        *,
        eval_run_id: str,
        suite: str,
        idempotency_key: str,
        request_payload: dict[str, str],
    ) -> None:
        deadline = time.monotonic() + REQUEST_TIMEOUT_SECONDS
        row = None
        while time.monotonic() < deadline:
            with closing(sqlite3.connect(self.db_path)) as conn:
                row = conn.execute(
                    """
                    SELECT
                        eval_run_id,
                        suite,
                        status,
                        idempotency_key,
                        request_json,
                        metrics_json,
                        error_code,
                        error_message,
                        started_at,
                        completed_at
                    FROM eval_runs
                    WHERE eval_run_id = ?
                    """,
                    (eval_run_id,),
                ).fetchone()
            if row is not None and row[2] in {"succeeded", "failed"}:
                break
            time.sleep(0.1)

        self.assertIsNotNone(row, f"Eval run row missing for eval_run_id={eval_run_id}")
        assert row is not None
        self.assertEqual(row[0], eval_run_id)
        self.assertEqual(row[1], suite)
        self.assertIn(row[2], {"succeeded", "failed"})
        self.assertEqual(row[3], idempotency_key)
        self.assertEqual(json.loads(str(row[4])), request_payload)
        metrics_payload = json.loads(str(row[5])) if row[5] is not None else {}
        self.assertEqual(metrics_payload.get("suite"), suite)
        self.assertIn("aggregate", metrics_payload)
        self.assertIsInstance(metrics_payload.get("aggregate"), dict)
        self.assertIsInstance(metrics_payload.get("case_count"), int)
        if row[2] == "failed":
            self.assertIsInstance(row[6], str)
            self.assertTrue(row[6])
        self.assertIsNotNone(row[8])
        self.assertIsNotNone(row[9])

    def _seed_eval_run_row(
        self,
        *,
        eval_run_id: str,
        suite: str,
        status: str,
        metrics: dict,
        error_code: str | None = None,
        error_message: str | None = None,
        started_at: str | None = None,
        completed_at: str | None = None,
    ) -> None:
        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.execute(
                """
                INSERT INTO eval_runs (
                    eval_run_id,
                    suite,
                    status,
                    metrics_json,
                    error_code,
                    error_message,
                    idempotency_key,
                    request_json,
                    started_at,
                    completed_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    eval_run_id,
                    suite,
                    status,
                    json.dumps(metrics, separators=(",", ":")),
                    error_code,
                    error_message,
                    f"seed-{eval_run_id}",
                    json.dumps({"suite": suite}, separators=(",", ":")),
                    started_at,
                    completed_at,
                ),
            )
            conn.commit()

    def _assert_interview_session_row_persisted(self, *, session_id: str, job_spec_id: str, candidate_id: str) -> None:
        with closing(sqlite3.connect(self.db_path)) as conn:
            row = conn.execute(
                """
                SELECT session_id, job_spec_id, candidate_id, mode, status, version
                FROM interview_sessions
                WHERE session_id = ?
                """,
                (session_id,),
            ).fetchone()

        self.assertIsNotNone(row, f"Interview session row missing for session_id={session_id}")
        assert row is not None
        self.assertEqual(row[0], session_id)
        self.assertEqual(row[1], job_spec_id)
        self.assertEqual(row[2], candidate_id)
        self.assertIn(row[3], {"mock_interview", "drill", "negotiation"})
        self.assertIn(row[4], {"in_progress", "completed"})
        self.assertGreaterEqual(int(row[5]), 1)

    def _assert_interview_response_row_persisted(self, *, session_id: str, idempotency_key: str) -> None:
        with closing(sqlite3.connect(self.db_path)) as conn:
            row = conn.execute(
                """
                SELECT session_id, idempotency_key, question_id, response_text, score
                FROM interview_session_responses
                WHERE session_id = ? AND idempotency_key = ?
                """,
                (session_id, idempotency_key),
            ).fetchone()

        self.assertIsNotNone(
            row,
            f"Interview response row missing for session_id={session_id}, idempotency_key={idempotency_key}",
        )
        assert row is not None
        self.assertEqual(row[0], session_id)
        self.assertEqual(row[1], idempotency_key)
        self.assertTrue(row[2])
        self.assertTrue(row[3])
        self.assertGreaterEqual(float(row[4]), 0.0)
        self.assertLessEqual(float(row[4]), 100.0)

    def _assert_feedback_report_row_persisted(
        self,
        *,
        feedback_report_id: str,
        session_id: str,
        idempotency_key: str,
    ) -> None:
        with closing(sqlite3.connect(self.db_path)) as conn:
            row = conn.execute(
                """
                SELECT feedback_report_id, session_id, idempotency_key, payload_json, version, supersedes_feedback_report_id
                FROM feedback_reports
                WHERE feedback_report_id = ?
                """,
                (feedback_report_id,),
            ).fetchone()

        self.assertIsNotNone(row, f"Feedback report row missing for feedback_report_id={feedback_report_id}")
        assert row is not None
        self.assertEqual(row[0], feedback_report_id)
        self.assertEqual(row[1], session_id)
        self.assertEqual(row[2], idempotency_key)
        payload = json.loads(str(row[3]))
        self.assertEqual(payload.get("feedback_report_id"), feedback_report_id)
        self.assertEqual(payload.get("session_id"), session_id)
        self.assertIsInstance(payload.get("overall_score"), (int, float))
        self.assertGreaterEqual(float(payload.get("overall_score", 0.0)), 0.0)
        self.assertLessEqual(float(payload.get("overall_score", 0.0)), 100.0)
        self.assertIsInstance(payload.get("answer_rewrites"), list)
        self.assertGreaterEqual(len(payload.get("answer_rewrites", [])), 1)
        self.assertIsInstance(payload.get("action_plan"), list)
        self.assertEqual(len(payload.get("action_plan", [])), 30)
        self.assertEqual([entry.get("day") for entry in payload.get("action_plan", [])], list(range(1, 31)))
        self.assertEqual(int(row[4]), int(payload.get("version", 0)))
        self.assertEqual(payload.get("supersedes_feedback_report_id"), row[5])

    def _assert_negotiation_plan_row_persisted(
        self,
        *,
        negotiation_plan_id: str,
        candidate_id: str,
        target_role: str,
        idempotency_key: str,
        expected_version: int = 1,
        expected_supersedes_negotiation_plan_id: str | None = None,
    ) -> None:
        with closing(sqlite3.connect(self.db_path)) as conn:
            row = conn.execute(
                """
                SELECT
                    negotiation_plan_id,
                    candidate_id,
                    target_role,
                    idempotency_key,
                    payload_json,
                    version,
                    supersedes_negotiation_plan_id
                FROM negotiation_plans
                WHERE negotiation_plan_id = ?
                """,
                (negotiation_plan_id,),
            ).fetchone()

        self.assertIsNotNone(row, f"Negotiation plan row missing for negotiation_plan_id={negotiation_plan_id}")
        assert row is not None
        self.assertEqual(row[0], negotiation_plan_id)
        self.assertEqual(row[1], candidate_id)
        self.assertEqual(row[2], target_role)
        self.assertEqual(row[3], idempotency_key)
        self.assertEqual(int(row[5]), expected_version)
        self.assertEqual(row[6], expected_supersedes_negotiation_plan_id)
        payload = json.loads(str(row[4]))
        self.assertEqual(payload.get("negotiation_plan_id"), negotiation_plan_id)
        self.assertEqual(payload.get("candidate_id"), candidate_id)
        self.assertEqual(payload.get("target_role"), target_role)
        self.assertEqual(payload.get("version"), expected_version)
        self.assertEqual(payload.get("supersedes_negotiation_plan_id"), expected_supersedes_negotiation_plan_id)
        self.assertIsInstance(payload.get("compensation_targets"), dict)
        compensation_targets = payload.get("compensation_targets", {})
        self.assertIn("recommended_counter_base_salary", compensation_targets)
        self.assertIn("market_reference_base_salary", compensation_targets)
        self.assertIn("confidence", compensation_targets)
        anchor_band = payload.get("anchor_band")
        self.assertIsInstance(anchor_band, dict)
        assert isinstance(anchor_band, dict)
        self.assertLessEqual(anchor_band.get("floor_base_salary", 0), anchor_band.get("target_base_salary", 0))
        self.assertLessEqual(anchor_band.get("target_base_salary", 0), anchor_band.get("ceiling_base_salary", 0))
        concession_ladder = payload.get("concession_ladder")
        self.assertIsInstance(concession_ladder, list)
        assert isinstance(concession_ladder, list)
        self.assertGreaterEqual(len(concession_ladder), 1)
        self.assertEqual([item.get("step") for item in concession_ladder], list(range(1, len(concession_ladder) + 1)))
        self.assertIsInstance(payload.get("objection_playbook"), list)
        self.assertGreaterEqual(len(payload.get("objection_playbook", [])), 1)
        follow_up_plan = payload.get("follow_up_plan")
        self.assertIsInstance(follow_up_plan, dict)
        assert isinstance(follow_up_plan, dict)
        self.assertIsInstance(follow_up_plan.get("thank_you_note"), dict)
        self.assertIsInstance(follow_up_plan.get("recruiter_cadence"), list)
        self.assertGreaterEqual(len(follow_up_plan.get("recruiter_cadence", [])), 1)
        self.assertIsInstance(follow_up_plan.get("outcome_branches"), list)
        self.assertGreaterEqual(len(follow_up_plan.get("outcome_branches", [])), 1)
        self.assertIsInstance(payload.get("talking_points"), list)
        self.assertIsInstance(payload.get("leverage_signals"), list)
        self.assertIsInstance(payload.get("risk_signals"), list)
        self.assertIsInstance(payload.get("evidence_links"), list)
        self.assertIsInstance(payload.get("follow_up_actions"), list)
        self.assertGreaterEqual(len(payload.get("follow_up_actions", [])), 1)

    def _assert_trajectory_plan_row_persisted(
        self,
        *,
        trajectory_plan_id: str,
        candidate_id: str,
        target_role: str,
        idempotency_key: str,
        expected_version: int = 1,
        expected_supersedes_trajectory_plan_id: str | None = None,
    ) -> None:
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

        self.assertIsNotNone(row, f"Trajectory plan row missing for trajectory_plan_id={trajectory_plan_id}")
        assert row is not None
        self.assertEqual(row[0], trajectory_plan_id)
        self.assertEqual(row[1], candidate_id)
        self.assertEqual(row[2], target_role)
        self.assertEqual(row[3], idempotency_key)
        self.assertEqual(int(row[5]), expected_version)
        self.assertEqual(row[6], expected_supersedes_trajectory_plan_id)
        payload = json.loads(str(row[4]))
        self.assertEqual(payload.get("trajectory_plan_id"), trajectory_plan_id)
        self.assertEqual(payload.get("candidate_id"), candidate_id)
        self.assertEqual(payload.get("target_role"), target_role)
        self.assertEqual(payload.get("version"), expected_version)
        self.assertEqual(payload.get("supersedes_trajectory_plan_id"), expected_supersedes_trajectory_plan_id)
        self.assertIsInstance(payload.get("milestones"), list)
        self.assertGreaterEqual(len(payload.get("milestones", [])), 1)

    def _assert_ingestion_accepted_response(self, body: dict) -> str:
        self.assertIsInstance(body, dict)
        self.assertIn("data", body)
        self.assertIn("meta", body)
        self.assertIn("error", body)
        self.assertIsNone(body["error"])

        data = body["data"]
        self.assertIsInstance(data, dict)
        self.assertEqual(data.get("status"), "queued")
        ingestion_id = data.get("ingestion_id")
        self.assertIsInstance(ingestion_id, str)
        self.assertTrue(ingestion_id)

        self._assert_meta(body["meta"])
        return ingestion_id

    def _assert_ingestion_status_response(self, body: dict, ingestion_id: str) -> None:
        self.assertIsInstance(body, dict)
        self.assertIn("data", body)
        self.assertIn("meta", body)
        self.assertIn("error", body)
        self.assertIsNone(body["error"])

        data = body["data"]
        self.assertIsInstance(data, dict)
        self.assertEqual(data.get("ingestion_id"), ingestion_id)
        self.assertIn(data.get("status"), {"queued", "running", "succeeded", "failed", "canceled"})
        self.assertIsInstance(data.get("current_stage"), str)
        self.assertTrue(data.get("current_stage"))

        self._assert_meta(body["meta"])

    def _assert_meta(self, meta: dict) -> None:
        self.assertIsInstance(meta, dict)
        self.assertIsInstance(meta.get("request_id"), str)
        self.assertTrue(meta.get("request_id"))

        timestamp = meta.get("timestamp")
        self.assertIsInstance(timestamp, str)
        self.assertTrue(timestamp)
        parsed_timestamp = timestamp.replace("Z", "+00:00")
        datetime.fromisoformat(parsed_timestamp)


if __name__ == "__main__":
    unittest.main(verbosity=2)
