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
        env.setdefault("JOBCOACH_DB_PATH", str(self._db_path))
        env.setdefault("SQLITE_DB_PATH", str(self._db_path))
        env.setdefault("DATABASE_URL", f"sqlite:///{self._db_path}")

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
        probe_path = f"{API_PREFIX}/job-ingestions/contract-readiness-probe"
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
