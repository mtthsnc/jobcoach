from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4


@dataclass(frozen=True)
class JobIngestionRecord:
    ingestion_id: str
    idempotency_key: str
    source_type: str
    source_value: str
    target_locale: str
    status: str
    current_stage: str
    progress_pct: int | None
    result_job_spec_id: str | None
    error_code: str | None
    error_message: str | None
    error_retryable: bool | None
    error_details: list[dict[str, Any]] | None


@dataclass(frozen=True)
class CreateResult:
    record: JobIngestionRecord
    created: bool


class SQLiteJobIngestionRepository:
    def __init__(self, db_path: str | Path) -> None:
        self._db_path = str(db_path)

    def create_or_get(
        self,
        *,
        idempotency_key: str,
        source_type: str,
        source_value: str,
        target_locale: str,
    ) -> CreateResult:
        ingestion_id = f"ing_{uuid4().hex}"

        with closing(self._connect()) as connection:
            with connection:
                try:
                    connection.execute(
                        """
                        INSERT INTO job_ingestions (
                            ingestion_id,
                            idempotency_key,
                            source_type,
                            source_value,
                            target_locale,
                            status,
                            current_stage
                        )
                        VALUES (?, ?, ?, ?, ?, 'queued', 'queued')
                        """,
                        (ingestion_id, idempotency_key, source_type, source_value, target_locale),
                    )
                    row = connection.execute(
                        "SELECT * FROM job_ingestions WHERE ingestion_id = ?",
                        (ingestion_id,),
                    ).fetchone()
                    if row is None:
                        raise RuntimeError("Inserted ingestion row could not be loaded")
                    return CreateResult(record=_row_to_record(row), created=True)
                except sqlite3.IntegrityError as exc:
                    if "idempotency_key" not in str(exc):
                        raise

                    row = connection.execute(
                        "SELECT * FROM job_ingestions WHERE idempotency_key = ?",
                        (idempotency_key,),
                    ).fetchone()
                    if row is None:
                        raise RuntimeError("Idempotent lookup failed after unique key collision")

                    return CreateResult(record=_row_to_record(row), created=False)

    def get_by_id(self, ingestion_id: str) -> JobIngestionRecord | None:
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT * FROM job_ingestions WHERE ingestion_id = ?",
                (ingestion_id,),
            ).fetchone()

        return _row_to_record(row) if row is not None else None

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._db_path)
        connection.row_factory = sqlite3.Row
        return connection


def _row_to_record(row: sqlite3.Row) -> JobIngestionRecord:
    error_details: list[dict[str, Any]] | None = None
    raw_error_details = row["error_details_json"]
    if raw_error_details:
        try:
            decoded = json.loads(raw_error_details)
        except json.JSONDecodeError:
            decoded = None
        if isinstance(decoded, list):
            error_details = [item for item in decoded if isinstance(item, dict)]

    return JobIngestionRecord(
        ingestion_id=row["ingestion_id"],
        idempotency_key=row["idempotency_key"],
        source_type=row["source_type"],
        source_value=row["source_value"],
        target_locale=row["target_locale"],
        status=row["status"],
        current_stage=row["current_stage"],
        progress_pct=row["progress_pct"],
        result_job_spec_id=row["result_job_spec_id"],
        error_code=row["error_code"],
        error_message=row["error_message"],
        error_retryable=bool(row["error_retryable"]) if row["error_retryable"] is not None else None,
        error_details=error_details,
    )
