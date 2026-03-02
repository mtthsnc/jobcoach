from __future__ import annotations

import json
import sqlite3
from packages.db.sqlite import connect_row_factory
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
class CandidateIngestionRecord:
    ingestion_id: str
    idempotency_key: str
    candidate_id: str | None
    cv_text: str | None
    cv_document_ref: str | None
    story_notes: list[str] | None
    target_roles: list[str] | None
    target_locale: str
    status: str
    current_stage: str
    progress_pct: int | None
    result_candidate_id: str | None
    error_code: str | None
    error_message: str | None
    error_retryable: bool | None
    error_details: list[dict[str, Any]] | None


@dataclass(frozen=True)
class CreateResult:
    record: JobIngestionRecord
    created: bool


@dataclass(frozen=True)
class CandidateCreateResult:
    record: CandidateIngestionRecord
    created: bool


@dataclass(frozen=True)
class TaxonomyMappingRecord:
    taxonomy_version: str
    input_term: str
    canonical_term: str
    confidence: float


@dataclass(frozen=True)
class JobSpecReviewResult:
    status: str
    job_spec: dict[str, Any] | None
    current_version: int | None


@dataclass(frozen=True)
class InterviewResponseResult:
    status: str
    session: dict[str, Any] | None
    current_version: int | None


@dataclass(frozen=True)
class FeedbackReportCreateResult:
    status: str
    report: dict[str, Any] | None
    current_version: int | None


@dataclass(frozen=True)
class TrajectoryPlanCreateResult:
    status: str
    plan: dict[str, Any] | None
    current_version: int | None


@dataclass(frozen=True)
class NegotiationPlanCreateResult:
    status: str
    plan: dict[str, Any] | None
    current_version: int | None


@dataclass(frozen=True)
class EvalRunCreateResult:
    status: str
    eval_run: dict[str, Any] | None


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

    def create_or_get_candidate(
        self,
        *,
        idempotency_key: str,
        candidate_id: str | None,
        cv_text: str | None,
        cv_document_ref: str | None,
        story_notes: list[str] | None,
        target_roles: list[str] | None,
        target_locale: str,
    ) -> CandidateCreateResult:
        ingestion_id = f"ing_{uuid4().hex}"
        story_notes_json = (
            json.dumps(story_notes, separators=(",", ":"), ensure_ascii=False) if story_notes is not None else None
        )
        target_roles_json = (
            json.dumps(target_roles, separators=(",", ":"), ensure_ascii=False) if target_roles is not None else None
        )

        with closing(self._connect()) as connection:
            with connection:
                try:
                    connection.execute(
                        """
                        INSERT INTO candidate_ingestions (
                            ingestion_id,
                            idempotency_key,
                            candidate_id,
                            cv_text,
                            cv_document_ref,
                            story_notes_json,
                            target_roles_json,
                            target_locale,
                            status,
                            current_stage
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'queued', 'queued')
                        """,
                        (
                            ingestion_id,
                            idempotency_key,
                            candidate_id,
                            cv_text,
                            cv_document_ref,
                            story_notes_json,
                            target_roles_json,
                            target_locale,
                        ),
                    )
                    row = connection.execute(
                        "SELECT * FROM candidate_ingestions WHERE ingestion_id = ?",
                        (ingestion_id,),
                    ).fetchone()
                    if row is None:
                        raise RuntimeError("Inserted candidate ingestion row could not be loaded")
                    return CandidateCreateResult(record=_row_to_candidate_record(row), created=True)
                except sqlite3.IntegrityError as exc:
                    if "idempotency_key" not in str(exc):
                        raise

                    row = connection.execute(
                        "SELECT * FROM candidate_ingestions WHERE idempotency_key = ?",
                        (idempotency_key,),
                    ).fetchone()
                    if row is None:
                        raise RuntimeError("Idempotent lookup failed after unique key collision")

                    return CandidateCreateResult(record=_row_to_candidate_record(row), created=False)

    def get_candidate_by_id(self, ingestion_id: str) -> CandidateIngestionRecord | None:
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT * FROM candidate_ingestions WHERE ingestion_id = ?",
                (ingestion_id,),
            ).fetchone()

        return _row_to_candidate_record(row) if row is not None else None

    def get_taxonomy_mapping(self, *, taxonomy_version: str, input_term: str) -> TaxonomyMappingRecord | None:
        with closing(self._connect()) as connection:
            row = connection.execute(
                """
                SELECT taxonomy_version, input_term, canonical_term, confidence
                FROM taxonomy_mappings
                WHERE taxonomy_version = ? AND input_term = ?
                """,
                (taxonomy_version, input_term),
            ).fetchone()

        return _row_to_taxonomy_mapping(row) if row is not None else None

    def create_or_get_taxonomy_mapping(
        self,
        *,
        taxonomy_version: str,
        input_term: str,
        canonical_term: str,
        confidence: float,
    ) -> TaxonomyMappingRecord:
        mapping_id = f"map_{uuid4().hex}"

        with closing(self._connect()) as connection:
            with connection:
                connection.execute(
                    """
                    INSERT OR IGNORE INTO taxonomy_mappings (
                        mapping_id,
                        taxonomy_version,
                        input_term,
                        canonical_term,
                        confidence
                    )
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        mapping_id,
                        taxonomy_version,
                        input_term,
                        canonical_term,
                        float(confidence),
                    ),
                )
                row = connection.execute(
                    """
                    SELECT taxonomy_version, input_term, canonical_term, confidence
                    FROM taxonomy_mappings
                    WHERE taxonomy_version = ? AND input_term = ?
                    """,
                    (taxonomy_version, input_term),
                ).fetchone()

        if row is None:
            raise RuntimeError("taxonomy mapping row could not be loaded after create-or-get")

        return _row_to_taxonomy_mapping(row)

    def create_or_get_eval_run(
        self,
        *,
        idempotency_key: str,
        request_payload: dict[str, Any],
        suite: str,
    ) -> EvalRunCreateResult:
        normalized_idempotency_key = str(idempotency_key).strip()
        if not normalized_idempotency_key:
            raise ValueError("idempotency_key must be a non-empty string")

        normalized_suite = str(suite).strip()
        if not normalized_suite:
            raise ValueError("suite must be a non-empty string")

        request_json = _canonical_json(request_payload)
        eval_run_id = f"eval_{uuid4().hex}"

        with closing(self._connect()) as connection:
            with connection:
                existing_row = connection.execute(
                    """
                    SELECT
                        eval_run_id,
                        suite,
                        status,
                        metrics_json,
                        error_code,
                        error_message,
                        created_at,
                        started_at,
                        completed_at,
                        request_json
                    FROM eval_runs
                    WHERE idempotency_key = ?
                    """,
                    (normalized_idempotency_key,),
                ).fetchone()
                if existing_row is not None:
                    existing_request_json_raw = existing_row["request_json"]
                    existing_request_json = (
                        str(existing_request_json_raw)
                        if isinstance(existing_request_json_raw, str)
                        else ""
                    )
                    is_replay = (
                        existing_request_json == request_json
                        if existing_request_json
                        else str(existing_row["suite"]) == normalized_suite
                    )
                    return EvalRunCreateResult(
                        status="idempotent_replay" if is_replay else "idempotency_conflict",
                        eval_run=_row_to_eval_run(existing_row),
                    )

                try:
                    connection.execute(
                        """
                        INSERT INTO eval_runs (
                            eval_run_id,
                            suite,
                            status,
                            idempotency_key,
                            request_json
                        )
                        VALUES (?, ?, 'queued', ?, ?)
                        """,
                        (
                            eval_run_id,
                            normalized_suite,
                            normalized_idempotency_key,
                            request_json,
                        ),
                    )
                except sqlite3.IntegrityError as exc:
                    if "idempotency_key" not in str(exc):
                        raise
                    row = connection.execute(
                        """
                        SELECT
                            eval_run_id,
                            suite,
                            status,
                            metrics_json,
                            error_code,
                            error_message,
                            created_at,
                            started_at,
                            completed_at,
                            request_json
                        FROM eval_runs
                        WHERE idempotency_key = ?
                        """,
                        (normalized_idempotency_key,),
                    ).fetchone()
                    if row is None:
                        raise RuntimeError("Eval run idempotent lookup failed after unique key collision")
                    existing_request_json_raw = row["request_json"]
                    existing_request_json = (
                        str(existing_request_json_raw)
                        if isinstance(existing_request_json_raw, str)
                        else ""
                    )
                    is_replay = (
                        existing_request_json == request_json
                        if existing_request_json
                        else str(row["suite"]) == normalized_suite
                    )
                    return EvalRunCreateResult(
                        status="idempotent_replay" if is_replay else "idempotency_conflict",
                        eval_run=_row_to_eval_run(row),
                    )

                created_row = connection.execute(
                    """
                    SELECT
                        eval_run_id,
                        suite,
                        status,
                        metrics_json,
                        error_code,
                        error_message,
                        created_at,
                        started_at,
                        completed_at
                    FROM eval_runs
                    WHERE eval_run_id = ?
                    """,
                    (eval_run_id,),
                ).fetchone()
                if created_row is None:
                    raise RuntimeError("Inserted eval run row could not be loaded")
                created_payload = _row_to_eval_run(created_row)
                if created_payload is None:
                    raise RuntimeError("Inserted eval run payload could not be normalized")
                self._enqueue_eval_run_lifecycle_event(
                    connection=connection,
                    eval_run_payload=created_payload,
                    lifecycle_status="queued",
                )
                return EvalRunCreateResult(
                    status="created",
                    eval_run=created_payload,
                )

    def get_eval_run_by_id(self, eval_run_id: str) -> dict[str, Any] | None:
        with closing(self._connect()) as connection:
            row = connection.execute(
                """
                SELECT
                    eval_run_id,
                    suite,
                    status,
                    metrics_json,
                    error_code,
                    error_message,
                    created_at,
                    started_at,
                    completed_at
                FROM eval_runs
                WHERE eval_run_id = ?
                """,
                (eval_run_id,),
            ).fetchone()

        return _row_to_eval_run(row) if row is not None else None

    def claim_next_queued_eval_run(self) -> dict[str, Any] | None:
        with closing(self._connect()) as connection:
            with connection:
                for _ in range(32):
                    candidate_row = connection.execute(
                        """
                        SELECT eval_run_id
                        FROM eval_runs
                        WHERE status = 'queued'
                        ORDER BY created_at ASC, eval_run_id ASC
                        LIMIT 1
                        """
                    ).fetchone()
                    if candidate_row is None:
                        return None

                    eval_run_id = str(candidate_row["eval_run_id"])
                    claim_cursor = connection.execute(
                        """
                        UPDATE eval_runs
                        SET status = 'running',
                            started_at = COALESCE(started_at, CURRENT_TIMESTAMP),
                            error_code = NULL,
                            error_message = NULL
                        WHERE eval_run_id = ?
                          AND status = 'queued'
                        """,
                        (eval_run_id,),
                    )
                    if claim_cursor.rowcount != 1:
                        continue

                    claimed_row = connection.execute(
                        """
                        SELECT
                            eval_run_id,
                            suite,
                            status,
                            metrics_json,
                            error_code,
                            error_message,
                            created_at,
                            started_at,
                            completed_at
                        FROM eval_runs
                        WHERE eval_run_id = ?
                        """,
                        (eval_run_id,),
                    ).fetchone()
                    return _row_to_eval_run(claimed_row) if claimed_row is not None else None
        return None

    def mark_eval_run_running(self, *, eval_run_id: str) -> dict[str, Any] | None:
        normalized_eval_run_id = str(eval_run_id).strip()
        if not normalized_eval_run_id:
            raise ValueError("eval_run_id must be a non-empty string")

        with closing(self._connect()) as connection:
            with connection:
                connection.execute(
                    """
                    UPDATE eval_runs
                    SET status = 'running',
                        started_at = COALESCE(started_at, CURRENT_TIMESTAMP),
                        error_code = NULL,
                        error_message = NULL
                    WHERE eval_run_id = ?
                      AND status = 'queued'
                    """,
                    (normalized_eval_run_id,),
                )
                row = connection.execute(
                    """
                    SELECT
                        eval_run_id,
                        suite,
                        status,
                        metrics_json,
                        error_code,
                        error_message,
                        created_at,
                        started_at,
                        completed_at
                    FROM eval_runs
                    WHERE eval_run_id = ?
                    """,
                    (normalized_eval_run_id,),
                ).fetchone()

        return _row_to_eval_run(row) if row is not None else None

    def complete_eval_run(
        self,
        *,
        eval_run_id: str,
        status: str,
        metrics: dict[str, Any] | None = None,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> dict[str, Any] | None:
        normalized_eval_run_id = str(eval_run_id).strip()
        if not normalized_eval_run_id:
            raise ValueError("eval_run_id must be a non-empty string")

        normalized_status = str(status).strip()
        if normalized_status not in {"succeeded", "failed"}:
            raise ValueError("status must be one of: succeeded, failed")

        normalized_metrics = metrics if isinstance(metrics, dict) else {}
        metrics_json = _canonical_json(normalized_metrics)
        normalized_error_code = None if normalized_status == "succeeded" else error_code
        normalized_error_message = None if normalized_status == "succeeded" else error_message

        with closing(self._connect()) as connection:
            with connection:
                transition_cursor = connection.execute(
                    """
                    UPDATE eval_runs
                    SET status = ?,
                        metrics_json = ?,
                        error_code = ?,
                        error_message = ?,
                        started_at = COALESCE(started_at, CURRENT_TIMESTAMP),
                        completed_at = CURRENT_TIMESTAMP
                    WHERE eval_run_id = ?
                      AND status IN ('queued', 'running')
                    """,
                    (
                        normalized_status,
                        metrics_json,
                        normalized_error_code,
                        normalized_error_message,
                        normalized_eval_run_id,
                    ),
                )
                row = connection.execute(
                    """
                    SELECT
                        eval_run_id,
                        suite,
                        status,
                        metrics_json,
                        error_code,
                        error_message,
                        created_at,
                        started_at,
                        completed_at
                    FROM eval_runs
                    WHERE eval_run_id = ?
                    """,
                    (normalized_eval_run_id,),
                ).fetchone()
                payload = _row_to_eval_run(row) if row is not None else None
                if transition_cursor.rowcount == 1 and payload is not None:
                    self._enqueue_eval_run_lifecycle_event(
                        connection=connection,
                        eval_run_payload=payload,
                        lifecycle_status=normalized_status,
                    )

        return payload

    def _enqueue_eval_run_lifecycle_event(
        self,
        *,
        connection: sqlite3.Connection,
        eval_run_payload: dict[str, Any],
        lifecycle_status: str,
    ) -> None:
        normalized_status = str(lifecycle_status).strip()
        if normalized_status not in {"queued", "succeeded", "failed"}:
            raise ValueError("lifecycle_status must be one of: queued, succeeded, failed")

        eval_run_id = str(eval_run_payload.get("eval_run_id", "")).strip()
        suite = str(eval_run_payload.get("suite", "")).strip()
        if not eval_run_id or not suite:
            raise ValueError("eval_run_payload must include eval_run_id and suite")

        event_id = _build_eval_run_lifecycle_event_id(eval_run_id=eval_run_id, status=normalized_status)
        event_type = f"eval_run.{normalized_status}"
        payload = _build_eval_run_lifecycle_event_payload(
            eval_run_payload=eval_run_payload,
            lifecycle_status=normalized_status,
        )
        available_at_raw = payload.get("completed_at") or payload.get("started_at") or payload.get("created_at")
        available_at = str(available_at_raw) if isinstance(available_at_raw, str) and available_at_raw.strip() else None
        connection.execute(
            """
            INSERT OR IGNORE INTO outbox_events (
                event_id,
                aggregate_type,
                aggregate_id,
                event_type,
                payload_json,
                available_at
            )
            VALUES (?, 'eval_run', ?, ?, ?, COALESCE(?, CURRENT_TIMESTAMP))
            """,
            (
                event_id,
                eval_run_id,
                event_type,
                _canonical_json(payload),
                available_at,
            ),
        )

    def persist_candidate_profile(self, *, ingestion_id: str, candidate_profile: dict[str, Any]) -> str:
        target_roles = candidate_profile.get("target_roles")
        target_roles_json = (
            json.dumps(target_roles, separators=(",", ":"), ensure_ascii=False) if target_roles is not None else None
        )
        experience_json = json.dumps(candidate_profile["experience"], separators=(",", ":"), ensure_ascii=False)
        skills_json = json.dumps(candidate_profile["skills"], separators=(",", ":"), ensure_ascii=False)

        with closing(self._connect()) as connection:
            with connection:
                connection.execute(
                    """
                    INSERT INTO candidate_profiles (
                        candidate_id,
                        ingestion_id,
                        summary,
                        target_roles_json,
                        experience_json,
                        skills_json,
                        parse_confidence,
                        version
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(candidate_id) DO UPDATE SET
                        ingestion_id = excluded.ingestion_id,
                        summary = excluded.summary,
                        target_roles_json = excluded.target_roles_json,
                        experience_json = excluded.experience_json,
                        skills_json = excluded.skills_json,
                        parse_confidence = excluded.parse_confidence,
                        version = excluded.version,
                        updated_at = CURRENT_TIMESTAMP
                    """,
                    (
                        candidate_profile["candidate_id"],
                        ingestion_id,
                        candidate_profile["summary"],
                        target_roles_json,
                        experience_json,
                        skills_json,
                        float(candidate_profile["parse_confidence"]),
                        int(candidate_profile.get("version", 1)),
                    ),
                )

                connection.execute(
                    """
                    UPDATE candidate_ingestions
                    SET result_candidate_id = COALESCE(result_candidate_id, ?),
                        updated_at = CURRENT_TIMESTAMP
                    WHERE ingestion_id = ?
                    """,
                    (candidate_profile["candidate_id"], ingestion_id),
                )

        return str(candidate_profile["candidate_id"])

    def get_candidate_profile_by_id(self, candidate_id: str) -> dict[str, Any] | None:
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT * FROM candidate_profiles WHERE candidate_id = ?",
                (candidate_id,),
            ).fetchone()

        return _row_to_candidate_profile(row) if row is not None else None

    def replace_candidate_storybank(self, *, candidate_id: str, stories: list[dict[str, Any]]) -> int:
        with closing(self._connect()) as connection:
            with connection:
                connection.execute(
                    "DELETE FROM candidate_storybank WHERE candidate_id = ?",
                    (candidate_id,),
                )

                for story in stories:
                    competencies_json = json.dumps(story.get("competencies", []), separators=(",", ":"), ensure_ascii=False)
                    metrics = story.get("metrics")
                    metrics_json = (
                        json.dumps(metrics, separators=(",", ":"), ensure_ascii=False)
                        if isinstance(metrics, list) and metrics
                        else None
                    )
                    connection.execute(
                        """
                        INSERT INTO candidate_storybank (
                            story_id,
                            candidate_id,
                            situation,
                            task,
                            action,
                            result,
                            competencies_json,
                            metrics_json,
                            evidence_quality
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            story["story_id"],
                            candidate_id,
                            story["situation"],
                            story["task"],
                            story["action"],
                            story["result"],
                            competencies_json,
                            metrics_json,
                            float(story["evidence_quality"]),
                        ),
                    )

        return len(stories)

    def get_candidate_storybank(self, *, candidate_id: str) -> list[dict[str, Any]]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                """
                SELECT story_id, situation, task, action, result, competencies_json, metrics_json, evidence_quality
                FROM candidate_storybank
                WHERE candidate_id = ?
                ORDER BY created_at ASC, story_id ASC
                """,
                (candidate_id,),
            ).fetchall()

        stories: list[dict[str, Any]] = []
        for row in rows:
            story: dict[str, Any] = {
                "story_id": row["story_id"],
                "situation": row["situation"],
                "task": row["task"],
                "action": row["action"],
                "result": row["result"],
                "competencies": _decode_json_string_list(row["competencies_json"]),
                "evidence_quality": row["evidence_quality"],
            }
            if row["metrics_json"] is not None:
                story["metrics"] = _decode_json_string_list(row["metrics_json"])
            stories.append(story)
        return stories

    def list_candidate_storybank(
        self,
        *,
        candidate_id: str,
        min_quality: float | None,
        competency: str | None,
        limit: int,
        cursor_offset: int,
    ) -> tuple[list[dict[str, Any]], str | None]:
        where_clauses = ["candidate_id = ?"]
        query_params: list[Any] = [candidate_id]

        if min_quality is not None:
            where_clauses.append("evidence_quality >= ?")
            query_params.append(float(min_quality))

        if competency is not None:
            where_clauses.append("LOWER(competencies_json) LIKE ?")
            query_params.append(f'%"{competency.lower()}"%')

        query = f"""
            SELECT story_id, situation, task, action, result, competencies_json, metrics_json, evidence_quality
            FROM candidate_storybank
            WHERE {' AND '.join(where_clauses)}
            ORDER BY created_at ASC, story_id ASC
            LIMIT ? OFFSET ?
        """
        query_params.append(limit + 1)
        query_params.append(cursor_offset)

        with closing(self._connect()) as connection:
            rows = connection.execute(query, tuple(query_params)).fetchall()

        has_more = len(rows) > limit
        page_rows = rows[:limit]

        stories: list[dict[str, Any]] = []
        for row in page_rows:
            story: dict[str, Any] = {
                "story_id": row["story_id"],
                "situation": row["situation"],
                "task": row["task"],
                "action": row["action"],
                "result": row["result"],
                "competencies": _decode_json_string_list(row["competencies_json"]),
                "evidence_quality": row["evidence_quality"],
            }
            if row["metrics_json"] is not None:
                story["metrics"] = _decode_json_string_list(row["metrics_json"])
            stories.append(story)

        next_cursor = str(cursor_offset + limit) if has_more else None
        return stories, next_cursor

    def create_interview_session(self, *, interview_session: dict[str, Any]) -> str:
        questions_json = json.dumps(interview_session["questions"], separators=(",", ":"), ensure_ascii=False)
        scores_json = json.dumps(interview_session["scores"], separators=(",", ":"), ensure_ascii=False)
        root_cause_tags = interview_session.get("root_cause_tags")
        root_cause_tags_json = (
            json.dumps(root_cause_tags, separators=(",", ":"), ensure_ascii=False)
            if isinstance(root_cause_tags, list)
            else None
        )

        with closing(self._connect()) as connection:
            with connection:
                connection.execute(
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
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        interview_session["session_id"],
                        interview_session["job_spec_id"],
                        interview_session["candidate_id"],
                        interview_session.get("mode", "mock_interview"),
                        interview_session.get("status", "in_progress"),
                        questions_json,
                        scores_json,
                        float(interview_session.get("overall_score", 0.0)),
                        root_cause_tags_json,
                        int(interview_session.get("version", 1)),
                        interview_session["created_at"],
                        interview_session["created_at"],
                    ),
                )

        return str(interview_session["session_id"])

    def get_interview_session_by_id(self, session_id: str) -> dict[str, Any] | None:
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT * FROM interview_sessions WHERE session_id = ?",
                (session_id,),
            ).fetchone()

        return _row_to_interview_session(row) if row is not None else None

    def create_or_get_feedback_report(
        self,
        *,
        idempotency_key: str,
        request_payload: dict[str, Any],
        feedback_report: dict[str, Any],
    ) -> FeedbackReportCreateResult:
        feedback_report_id = str(feedback_report.get("feedback_report_id", "")).strip()
        session_id = str(feedback_report.get("session_id", "")).strip()
        if not feedback_report_id or not session_id:
            raise ValueError("feedback_report must include non-empty feedback_report_id and session_id")

        request_json = _canonical_json(request_payload)
        expected_version_raw = request_payload.get("expected_version")
        expected_version: int | None = None
        if isinstance(expected_version_raw, int) and not isinstance(expected_version_raw, bool):
            expected_version = expected_version_raw

        with closing(self._connect()) as connection:
            with connection:
                session_row = connection.execute(
                    "SELECT 1 FROM interview_sessions WHERE session_id = ?",
                    (session_id,),
                ).fetchone()
                if session_row is None:
                    return FeedbackReportCreateResult(status="session_not_found", report=None, current_version=None)

                existing_row = connection.execute(
                    """
                    SELECT request_json, payload_json
                    FROM feedback_reports
                    WHERE idempotency_key = ?
                    """,
                    (idempotency_key,),
                ).fetchone()
                if existing_row is not None:
                    existing_request_json = str(existing_row["request_json"])
                    existing_payload = _decode_json_object(str(existing_row["payload_json"]))
                    existing_version = existing_payload.get("version")
                    current_version = int(existing_version) if isinstance(existing_version, int) else None
                    if existing_request_json == request_json:
                        return FeedbackReportCreateResult(
                            status="idempotent_replay",
                            report=existing_payload,
                            current_version=current_version,
                        )
                    return FeedbackReportCreateResult(
                        status="idempotency_conflict",
                        report=existing_payload,
                        current_version=current_version,
                    )

                latest_row = connection.execute(
                    """
                    SELECT feedback_report_id, payload_json, version
                    FROM feedback_reports
                    WHERE session_id = ?
                    ORDER BY version DESC, created_at DESC, feedback_report_id DESC
                    LIMIT 1
                    """,
                    (session_id,),
                ).fetchone()
                current_version = int(latest_row["version"]) if latest_row is not None else 0
                if expected_version is not None and expected_version != current_version:
                    latest_payload = (
                        _decode_json_object(str(latest_row["payload_json"])) if latest_row is not None else None
                    )
                    return FeedbackReportCreateResult(
                        status="version_conflict",
                        report=latest_payload,
                        current_version=current_version,
                    )

                report_payload = json.loads(json.dumps(feedback_report))
                next_version = current_version + 1
                report_payload["version"] = next_version
                supersedes_feedback_report_id: str | None = None
                if latest_row is not None:
                    supersedes_feedback_report_id = str(latest_row["feedback_report_id"])
                    report_payload["supersedes_feedback_report_id"] = supersedes_feedback_report_id
                payload_json = _canonical_json(report_payload)

                connection.execute(
                    """
                    INSERT INTO feedback_reports (
                        feedback_report_id,
                        session_id,
                        idempotency_key,
                        request_json,
                        payload_json,
                        version,
                        supersedes_feedback_report_id
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        feedback_report_id,
                        session_id,
                        idempotency_key,
                        request_json,
                        payload_json,
                        next_version,
                        supersedes_feedback_report_id,
                    ),
                )

                row = connection.execute(
                    "SELECT payload_json, version FROM feedback_reports WHERE feedback_report_id = ?",
                    (feedback_report_id,),
                ).fetchone()
                if row is None:
                    return FeedbackReportCreateResult(status="not_found", report=None, current_version=None)

                return FeedbackReportCreateResult(
                    status="created",
                    report=_decode_json_object(str(row["payload_json"])),
                    current_version=int(row["version"]),
                )

    def get_feedback_report_by_id(self, feedback_report_id: str) -> dict[str, Any] | None:
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT payload_json FROM feedback_reports WHERE feedback_report_id = ?",
                (feedback_report_id,),
            ).fetchone()

        return _row_to_feedback_report(row) if row is not None else None

    def create_or_get_negotiation_plan(
        self,
        *,
        idempotency_key: str,
        request_payload: dict[str, Any],
        negotiation_plan: dict[str, Any],
    ) -> NegotiationPlanCreateResult:
        negotiation_plan_id = str(negotiation_plan.get("negotiation_plan_id", "")).strip()
        candidate_id = str(negotiation_plan.get("candidate_id", "")).strip()
        target_role = str(negotiation_plan.get("target_role", "")).strip()
        if not negotiation_plan_id or not candidate_id or not target_role:
            raise ValueError(
                "negotiation_plan must include non-empty negotiation_plan_id, candidate_id, and target_role"
            )

        request_json = _canonical_json(request_payload)
        expected_version_raw = request_payload.get("expected_version")
        expected_version: int | None = None
        if isinstance(expected_version_raw, int) and not isinstance(expected_version_raw, bool):
            expected_version = expected_version_raw

        with closing(self._connect()) as connection:
            with connection:
                candidate_row = connection.execute(
                    "SELECT 1 FROM candidate_profiles WHERE candidate_id = ?",
                    (candidate_id,),
                ).fetchone()
                if candidate_row is None:
                    return NegotiationPlanCreateResult(status="candidate_not_found", plan=None, current_version=None)

                existing_row = connection.execute(
                    """
                    SELECT request_json, payload_json, version, supersedes_negotiation_plan_id
                    FROM negotiation_plans
                    WHERE idempotency_key = ?
                    """,
                    (idempotency_key,),
                ).fetchone()
                if existing_row is not None:
                    existing_request_json = str(existing_row["request_json"])
                    existing_payload = _row_to_negotiation_plan(existing_row)
                    existing_version_raw = existing_payload.get("version") if isinstance(existing_payload, dict) else None
                    existing_version = int(existing_row["version"]) if isinstance(existing_row["version"], int) else None
                    if existing_version is None and isinstance(existing_version_raw, int):
                        existing_version = int(existing_version_raw)
                    if existing_request_json == request_json:
                        return NegotiationPlanCreateResult(
                            status="idempotent_replay",
                            plan=existing_payload,
                            current_version=existing_version,
                        )
                    return NegotiationPlanCreateResult(
                        status="idempotency_conflict",
                        plan=existing_payload,
                        current_version=existing_version,
                    )

                latest_row = connection.execute(
                    """
                    SELECT negotiation_plan_id, payload_json, version, supersedes_negotiation_plan_id
                    FROM negotiation_plans
                    WHERE candidate_id = ? AND target_role = ?
                    ORDER BY version DESC, created_at DESC, negotiation_plan_id DESC
                    LIMIT 1
                    """,
                    (candidate_id, target_role),
                ).fetchone()
                current_version = int(latest_row["version"]) if latest_row is not None else 0
                if expected_version is not None and expected_version != current_version:
                    latest_payload = _row_to_negotiation_plan(latest_row) if latest_row is not None else None
                    return NegotiationPlanCreateResult(
                        status="version_conflict",
                        plan=latest_payload,
                        current_version=current_version,
                    )

                plan_payload = json.loads(json.dumps(negotiation_plan))
                next_version = current_version + 1
                plan_payload["version"] = next_version
                supersedes_negotiation_plan_id: str | None = None
                if latest_row is not None:
                    supersedes_negotiation_plan_id = str(latest_row["negotiation_plan_id"])
                    plan_payload["supersedes_negotiation_plan_id"] = supersedes_negotiation_plan_id
                payload_json = _canonical_json(plan_payload)
                connection.execute(
                    """
                    INSERT INTO negotiation_plans (
                        negotiation_plan_id,
                        candidate_id,
                        target_role,
                        idempotency_key,
                        request_json,
                        payload_json,
                        version,
                        supersedes_negotiation_plan_id
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        negotiation_plan_id,
                        candidate_id,
                        target_role,
                        idempotency_key,
                        request_json,
                        payload_json,
                        next_version,
                        supersedes_negotiation_plan_id,
                    ),
                )

                row = connection.execute(
                    """
                    SELECT payload_json, version, supersedes_negotiation_plan_id
                    FROM negotiation_plans
                    WHERE negotiation_plan_id = ?
                    """,
                    (negotiation_plan_id,),
                ).fetchone()
                if row is None:
                    return NegotiationPlanCreateResult(status="not_found", plan=None, current_version=None)

                return NegotiationPlanCreateResult(
                    status="created",
                    plan=_row_to_negotiation_plan(row),
                    current_version=int(row["version"]),
                )

    def get_negotiation_plan_by_id(self, negotiation_plan_id: str) -> dict[str, Any] | None:
        with closing(self._connect()) as connection:
            row = connection.execute(
                """
                SELECT payload_json, version, supersedes_negotiation_plan_id
                FROM negotiation_plans
                WHERE negotiation_plan_id = ?
                """,
                (negotiation_plan_id,),
            ).fetchone()

        return _row_to_negotiation_plan(row) if row is not None else None

    def create_or_get_trajectory_plan(
        self,
        *,
        idempotency_key: str,
        request_payload: dict[str, Any],
        trajectory_plan: dict[str, Any],
    ) -> TrajectoryPlanCreateResult:
        trajectory_plan_id = str(trajectory_plan.get("trajectory_plan_id", "")).strip()
        candidate_id = str(trajectory_plan.get("candidate_id", "")).strip()
        target_role = str(trajectory_plan.get("target_role", "")).strip()
        if not trajectory_plan_id or not candidate_id or not target_role:
            raise ValueError(
                "trajectory_plan must include non-empty trajectory_plan_id, candidate_id, and target_role"
            )

        request_json = _canonical_json(request_payload)
        expected_version_raw = request_payload.get("expected_version")
        expected_version: int | None = None
        if isinstance(expected_version_raw, int) and not isinstance(expected_version_raw, bool):
            expected_version = expected_version_raw

        with closing(self._connect()) as connection:
            with connection:
                candidate_row = connection.execute(
                    "SELECT 1 FROM candidate_profiles WHERE candidate_id = ?",
                    (candidate_id,),
                ).fetchone()
                if candidate_row is None:
                    return TrajectoryPlanCreateResult(status="candidate_not_found", plan=None, current_version=None)

                existing_row = connection.execute(
                    """
                    SELECT request_json, payload_json, version, supersedes_trajectory_plan_id
                    FROM trajectory_plans
                    WHERE idempotency_key = ?
                    """,
                    (idempotency_key,),
                ).fetchone()
                if existing_row is not None:
                    existing_request_json = str(existing_row["request_json"])
                    existing_payload = _row_to_trajectory_plan(existing_row)
                    existing_version_raw = existing_payload.get("version") if isinstance(existing_payload, dict) else None
                    existing_version = int(existing_row["version"]) if isinstance(existing_row["version"], int) else None
                    if existing_version is None and isinstance(existing_version_raw, int):
                        existing_version = int(existing_version_raw)
                    if existing_request_json == request_json:
                        return TrajectoryPlanCreateResult(
                            status="idempotent_replay",
                            plan=existing_payload,
                            current_version=existing_version,
                        )
                    return TrajectoryPlanCreateResult(
                        status="idempotency_conflict",
                        plan=existing_payload,
                        current_version=existing_version,
                    )

                latest_row = connection.execute(
                    """
                    SELECT trajectory_plan_id, payload_json, version, supersedes_trajectory_plan_id
                    FROM trajectory_plans
                    WHERE candidate_id = ? AND target_role = ?
                    ORDER BY version DESC, created_at DESC, trajectory_plan_id DESC
                    LIMIT 1
                    """,
                    (candidate_id, target_role),
                ).fetchone()
                current_version = int(latest_row["version"]) if latest_row is not None else 0
                if expected_version is not None and expected_version != current_version:
                    latest_payload = _row_to_trajectory_plan(latest_row) if latest_row is not None else None
                    return TrajectoryPlanCreateResult(
                        status="version_conflict",
                        plan=latest_payload,
                        current_version=current_version,
                    )

                plan_payload = json.loads(json.dumps(trajectory_plan))
                next_version = current_version + 1
                plan_payload["version"] = next_version
                supersedes_trajectory_plan_id: str | None = None
                if latest_row is not None:
                    supersedes_trajectory_plan_id = str(latest_row["trajectory_plan_id"])
                    plan_payload["supersedes_trajectory_plan_id"] = supersedes_trajectory_plan_id
                payload_json = _canonical_json(plan_payload)
                connection.execute(
                    """
                    INSERT INTO trajectory_plans (
                        trajectory_plan_id,
                        candidate_id,
                        target_role,
                        idempotency_key,
                        request_json,
                        payload_json,
                        version,
                        supersedes_trajectory_plan_id
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        trajectory_plan_id,
                        candidate_id,
                        target_role,
                        idempotency_key,
                        request_json,
                        payload_json,
                        next_version,
                        supersedes_trajectory_plan_id,
                    ),
                )

                row = connection.execute(
                    """
                    SELECT payload_json, version, supersedes_trajectory_plan_id
                    FROM trajectory_plans
                    WHERE trajectory_plan_id = ?
                    """,
                    (trajectory_plan_id,),
                ).fetchone()
                if row is None:
                    return TrajectoryPlanCreateResult(status="not_found", plan=None, current_version=None)

                return TrajectoryPlanCreateResult(
                    status="created",
                    plan=_row_to_trajectory_plan(row),
                    current_version=int(row["version"]),
                )

    def get_trajectory_plan_by_id(self, trajectory_plan_id: str) -> dict[str, Any] | None:
        with closing(self._connect()) as connection:
            row = connection.execute(
                """
                SELECT payload_json, version, supersedes_trajectory_plan_id
                FROM trajectory_plans
                WHERE trajectory_plan_id = ?
                """,
                (trajectory_plan_id,),
            ).fetchone()

        return _row_to_trajectory_plan(row) if row is not None else None

    def get_latest_trajectory_plan_for_candidate(
        self,
        *,
        candidate_id: str,
        target_role: str | None = None,
    ) -> dict[str, Any] | None:
        with closing(self._connect()) as connection:
            if isinstance(target_role, str) and target_role.strip():
                row = connection.execute(
                    """
                    SELECT payload_json, version, supersedes_trajectory_plan_id
                    FROM trajectory_plans
                    WHERE candidate_id = ? AND target_role = ?
                    ORDER BY version DESC, created_at DESC, trajectory_plan_id DESC
                    LIMIT 1
                    """,
                    (candidate_id, target_role.strip()),
                ).fetchone()
            else:
                row = connection.execute(
                    """
                    SELECT payload_json, version, supersedes_trajectory_plan_id
                    FROM trajectory_plans
                    WHERE candidate_id = ?
                    ORDER BY created_at DESC, target_role ASC, version DESC, trajectory_plan_id DESC
                    LIMIT 1
                    """,
                    (candidate_id,),
                ).fetchone()

        return _row_to_trajectory_plan(row) if row is not None else None

    def list_interview_sessions_for_candidate(self, *, candidate_id: str) -> list[dict[str, Any]]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                """
                SELECT *
                FROM interview_sessions
                WHERE candidate_id = ?
                ORDER BY created_at ASC, session_id ASC
                """,
                (candidate_id,),
            ).fetchall()

        sessions: list[dict[str, Any]] = []
        for row in rows:
            session = _row_to_interview_session(row)
            if session is not None:
                sessions.append(session)
        return sessions

    def list_feedback_reports_for_candidate(self, *, candidate_id: str) -> list[dict[str, Any]]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                """
                SELECT fr.payload_json, fr.created_at
                FROM feedback_reports fr
                INNER JOIN interview_sessions isess ON isess.session_id = fr.session_id
                WHERE isess.candidate_id = ?
                ORDER BY fr.created_at ASC, fr.feedback_report_id ASC
                """,
                (candidate_id,),
            ).fetchall()

        reports: list[dict[str, Any]] = []
        for row in rows:
            payload = _decode_json_object(str(row["payload_json"]))
            if "generated_at" not in payload:
                payload["generated_at"] = row["created_at"]
            reports.append(payload)
        return reports

    def apply_interview_response(
        self,
        *,
        session_id: str,
        idempotency_key: str,
        request_payload: dict[str, Any],
        updated_session: dict[str, Any],
        question_id: str,
        response_text: str,
        score: float,
    ) -> InterviewResponseResult:
        request_json = _canonical_json(request_payload)
        questions_json = json.dumps(updated_session["questions"], separators=(",", ":"), ensure_ascii=False)
        scores_json = json.dumps(updated_session["scores"], separators=(",", ":"), ensure_ascii=False)
        root_cause_tags = updated_session.get("root_cause_tags")
        root_cause_tags_json = (
            json.dumps(root_cause_tags, separators=(",", ":"), ensure_ascii=False)
            if isinstance(root_cause_tags, list)
            else None
        )
        response_id = f"iresp_{uuid4().hex}"
        expected_version = int(updated_session.get("version", 2)) - 1

        with closing(self._connect()) as connection:
            with connection:
                current_row = connection.execute(
                    "SELECT * FROM interview_sessions WHERE session_id = ?",
                    (session_id,),
                ).fetchone()
                if current_row is None:
                    return InterviewResponseResult(status="not_found", session=None, current_version=None)

                existing_response_row = connection.execute(
                    """
                    SELECT request_json
                    FROM interview_session_responses
                    WHERE session_id = ? AND idempotency_key = ?
                    """,
                    (session_id, idempotency_key),
                ).fetchone()
                if existing_response_row is not None:
                    existing_request_json = str(existing_response_row["request_json"])
                    current_session = _row_to_interview_session(current_row)
                    if existing_request_json == request_json:
                        return InterviewResponseResult(
                            status="idempotent_replay",
                            session=current_session,
                            current_version=int(current_row["version"]),
                        )
                    return InterviewResponseResult(
                        status="idempotency_conflict",
                        session=current_session,
                        current_version=int(current_row["version"]),
                    )

                update_cursor = connection.execute(
                    """
                    UPDATE interview_sessions
                    SET questions_json = ?,
                        scores_json = ?,
                        overall_score = ?,
                        root_cause_tags_json = ?,
                        status = ?,
                        version = ?,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE session_id = ? AND version = ?
                    """,
                    (
                        questions_json,
                        scores_json,
                        float(updated_session["overall_score"]),
                        root_cause_tags_json,
                        updated_session.get("status", "in_progress"),
                        int(updated_session["version"]),
                        session_id,
                        expected_version,
                    ),
                )
                if update_cursor.rowcount != 1:
                    latest_row = connection.execute(
                        "SELECT * FROM interview_sessions WHERE session_id = ?",
                        (session_id,),
                    ).fetchone()
                    latest_version = int(latest_row["version"]) if latest_row is not None else None
                    return InterviewResponseResult(
                        status="version_conflict",
                        session=_row_to_interview_session(latest_row) if latest_row is not None else None,
                        current_version=latest_version,
                    )

                connection.execute(
                    """
                    INSERT INTO interview_session_responses (
                        response_id,
                        session_id,
                        idempotency_key,
                        request_json,
                        question_id,
                        response_text,
                        score
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        response_id,
                        session_id,
                        idempotency_key,
                        request_json,
                        question_id,
                        response_text,
                        float(score),
                    ),
                )

                updated_row = connection.execute(
                    "SELECT * FROM interview_sessions WHERE session_id = ?",
                    (session_id,),
                ).fetchone()
                if updated_row is None:
                    return InterviewResponseResult(status="not_found", session=None, current_version=None)

                return InterviewResponseResult(
                    status="updated",
                    session=_row_to_interview_session(updated_row),
                    current_version=int(updated_row["version"]),
                )

    def persist_job_spec(self, *, ingestion_id: str, job_spec: dict[str, Any]) -> str:
        responsibilities_json = json.dumps(job_spec["responsibilities"], separators=(",", ":"), ensure_ascii=False)
        requirements_json = json.dumps(job_spec["requirements"], separators=(",", ":"), ensure_ascii=False)
        competency_weights_json = json.dumps(job_spec["competency_weights"], separators=(",", ":"), ensure_ascii=False)
        evidence_spans = job_spec.get("evidence_spans")
        evidence_spans_json = (
            json.dumps(evidence_spans, separators=(",", ":"), ensure_ascii=False) if evidence_spans is not None else None
        )

        with closing(self._connect()) as connection:
            with connection:
                connection.execute(
                    """
                    INSERT INTO job_specs (
                        job_spec_id,
                        ingestion_id,
                        source_type,
                        source_value,
                        source_captured_at,
                        company,
                        role_title,
                        seniority_level,
                        location,
                        employment_type,
                        responsibilities_json,
                        requirements_json,
                        competency_weights_json,
                        evidence_spans_json,
                        extraction_confidence,
                        taxonomy_version,
                        version
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(job_spec_id) DO NOTHING
                    """,
                    (
                        job_spec["job_spec_id"],
                        ingestion_id,
                        job_spec["source"]["type"],
                        job_spec["source"]["value"],
                        job_spec["source"]["captured_at"],
                        job_spec.get("company"),
                        job_spec["role_title"],
                        job_spec.get("seniority_level"),
                        job_spec.get("location"),
                        job_spec.get("employment_type"),
                        responsibilities_json,
                        requirements_json,
                        competency_weights_json,
                        evidence_spans_json,
                        float(job_spec["extraction_confidence"]),
                        job_spec.get("taxonomy_version"),
                        int(job_spec.get("version", 1)),
                    ),
                )

                connection.execute(
                    """
                    UPDATE job_ingestions
                    SET result_job_spec_id = COALESCE(result_job_spec_id, ?),
                        updated_at = CURRENT_TIMESTAMP
                    WHERE ingestion_id = ?
                    """,
                    (job_spec["job_spec_id"], ingestion_id),
                )

        return str(job_spec["job_spec_id"])

    def get_job_spec_by_id(self, job_spec_id: str) -> dict[str, Any] | None:
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT * FROM job_specs WHERE job_spec_id = ?",
                (job_spec_id,),
            ).fetchone()

        return _row_to_job_spec(row) if row is not None else None

    def apply_job_spec_review(
        self,
        *,
        job_spec_id: str,
        expected_version: int,
        updated_job_spec: dict[str, Any],
        patch: dict[str, Any],
        review_notes: str | None,
        reviewed_by: str | None,
    ) -> JobSpecReviewResult:
        responsibilities_json = json.dumps(updated_job_spec["responsibilities"], separators=(",", ":"), ensure_ascii=False)
        requirements_json = json.dumps(updated_job_spec["requirements"], separators=(",", ":"), ensure_ascii=False)
        competency_weights_json = json.dumps(
            updated_job_spec["competency_weights"], separators=(",", ":"), ensure_ascii=False
        )
        evidence_spans = updated_job_spec.get("evidence_spans")
        evidence_spans_json = (
            json.dumps(evidence_spans, separators=(",", ":"), ensure_ascii=False) if evidence_spans is not None else None
        )
        patch_json = json.dumps(patch, separators=(",", ":"), ensure_ascii=False)
        result_version = expected_version + 1
        review_id = f"rev_{uuid4().hex}"

        with closing(self._connect()) as connection:
            with connection:
                current_row = connection.execute(
                    "SELECT * FROM job_specs WHERE job_spec_id = ?",
                    (job_spec_id,),
                ).fetchone()
                if current_row is None:
                    return JobSpecReviewResult(status="not_found", job_spec=None, current_version=None)

                current_version = int(current_row["version"])
                if current_version != expected_version:
                    return JobSpecReviewResult(
                        status="version_conflict",
                        job_spec=_row_to_job_spec(current_row),
                        current_version=current_version,
                    )

                update_cursor = connection.execute(
                    """
                    UPDATE job_specs
                    SET company = ?,
                        role_title = ?,
                        seniority_level = ?,
                        location = ?,
                        employment_type = ?,
                        responsibilities_json = ?,
                        requirements_json = ?,
                        competency_weights_json = ?,
                        evidence_spans_json = ?,
                        extraction_confidence = ?,
                        taxonomy_version = ?,
                        version = ?,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE job_spec_id = ? AND version = ?
                    """,
                    (
                        updated_job_spec.get("company"),
                        updated_job_spec["role_title"],
                        updated_job_spec.get("seniority_level"),
                        updated_job_spec.get("location"),
                        updated_job_spec.get("employment_type"),
                        responsibilities_json,
                        requirements_json,
                        competency_weights_json,
                        evidence_spans_json,
                        float(updated_job_spec["extraction_confidence"]),
                        updated_job_spec.get("taxonomy_version"),
                        result_version,
                        job_spec_id,
                        expected_version,
                    ),
                )
                if update_cursor.rowcount != 1:
                    latest_row = connection.execute(
                        "SELECT * FROM job_specs WHERE job_spec_id = ?",
                        (job_spec_id,),
                    ).fetchone()
                    latest_version = int(latest_row["version"]) if latest_row is not None else None
                    return JobSpecReviewResult(
                        status="version_conflict",
                        job_spec=_row_to_job_spec(latest_row) if latest_row is not None else None,
                        current_version=latest_version,
                    )

                connection.execute(
                    """
                    INSERT INTO job_spec_reviews (
                        review_id,
                        job_spec_id,
                        expected_version,
                        result_version,
                        patch_json,
                        review_notes,
                        reviewed_by
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        review_id,
                        job_spec_id,
                        expected_version,
                        result_version,
                        patch_json,
                        review_notes,
                        reviewed_by,
                    ),
                )

                updated_row = connection.execute(
                    "SELECT * FROM job_specs WHERE job_spec_id = ?",
                    (job_spec_id,),
                ).fetchone()
                if updated_row is None:
                    return JobSpecReviewResult(status="not_found", job_spec=None, current_version=None)

                return JobSpecReviewResult(
                    status="updated",
                    job_spec=_row_to_job_spec(updated_row),
                    current_version=int(updated_row["version"]),
                )

    def probe_readiness(self) -> tuple[bool, str | None]:
        try:
            with closing(self._connect()) as connection:
                connection.execute("SELECT 1").fetchone()
            return True, None
        except sqlite3.Error as exc:
            error_code = f"sqlite_{exc.__class__.__name__.lower()}"
            return False, error_code

    def _connect(self):
        return connect_row_factory(self._db_path)


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


def _row_to_candidate_record(row: sqlite3.Row) -> CandidateIngestionRecord:
    error_details: list[dict[str, Any]] | None = None
    raw_error_details = row["error_details_json"]
    if raw_error_details:
        try:
            decoded = json.loads(raw_error_details)
        except json.JSONDecodeError:
            decoded = None
        if isinstance(decoded, list):
            error_details = [item for item in decoded if isinstance(item, dict)]

    story_notes = _decode_json_string_list(row["story_notes_json"]) if row["story_notes_json"] else None
    target_roles = _decode_json_string_list(row["target_roles_json"]) if row["target_roles_json"] else None

    return CandidateIngestionRecord(
        ingestion_id=row["ingestion_id"],
        idempotency_key=row["idempotency_key"],
        candidate_id=row["candidate_id"],
        cv_text=row["cv_text"],
        cv_document_ref=row["cv_document_ref"],
        story_notes=story_notes,
        target_roles=target_roles,
        target_locale=row["target_locale"],
        status=row["status"],
        current_stage=row["current_stage"],
        progress_pct=row["progress_pct"],
        result_candidate_id=row["result_candidate_id"],
        error_code=row["error_code"],
        error_message=row["error_message"],
        error_retryable=bool(row["error_retryable"]) if row["error_retryable"] is not None else None,
        error_details=error_details,
    )


def _row_to_taxonomy_mapping(row: sqlite3.Row) -> TaxonomyMappingRecord:
    return TaxonomyMappingRecord(
        taxonomy_version=str(row["taxonomy_version"]),
        input_term=str(row["input_term"]),
        canonical_term=str(row["canonical_term"]),
        confidence=float(row["confidence"]),
    )


def _row_to_eval_run(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None

    payload: dict[str, Any] = {
        "eval_run_id": str(row["eval_run_id"]),
        "suite": str(row["suite"]),
        "status": str(row["status"]),
        "metrics": _decode_json_object(str(row["metrics_json"])) if row["metrics_json"] is not None else {},
    }
    if row["error_code"] is not None or row["error_message"] is not None:
        payload["error"] = {
            "code": str(row["error_code"]) if row["error_code"] is not None else "",
            "message": str(row["error_message"]) if row["error_message"] is not None else "",
        }
    if row["created_at"] is not None:
        payload["created_at"] = str(row["created_at"])
    if row["started_at"] is not None:
        payload["started_at"] = str(row["started_at"])
    if row["completed_at"] is not None:
        payload["completed_at"] = str(row["completed_at"])
    return payload


def _row_to_job_spec(row: sqlite3.Row) -> dict[str, Any]:
    responsibilities = _decode_json_list(row["responsibilities_json"])
    requirements = _decode_json_object(row["requirements_json"])
    competency_weights = _decode_json_object(row["competency_weights_json"])
    evidence_spans = _decode_json_list(row["evidence_spans_json"]) if row["evidence_spans_json"] else None

    payload: dict[str, Any] = {
        "job_spec_id": row["job_spec_id"],
        "source": {
            "type": row["source_type"],
            "value": row["source_value"],
            "captured_at": row["source_captured_at"],
        },
        "role_title": row["role_title"],
        "responsibilities": responsibilities,
        "requirements": requirements,
        "competency_weights": competency_weights,
        "extraction_confidence": row["extraction_confidence"],
        "version": row["version"],
    }

    if row["company"] is not None:
        payload["company"] = row["company"]
    if row["seniority_level"] is not None:
        payload["seniority_level"] = row["seniority_level"]
    if row["location"] is not None:
        payload["location"] = row["location"]
    if row["employment_type"] is not None:
        payload["employment_type"] = row["employment_type"]
    if row["taxonomy_version"] is not None:
        payload["taxonomy_version"] = row["taxonomy_version"]
    if evidence_spans:
        payload["evidence_spans"] = evidence_spans

    return payload


def _row_to_candidate_profile(row: sqlite3.Row) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "candidate_id": row["candidate_id"],
        "summary": row["summary"],
        "experience": _decode_json_list(row["experience_json"]),
        "skills": _decode_json_object(row["skills_json"]),
        "parse_confidence": row["parse_confidence"],
        "version": row["version"],
    }

    if row["target_roles_json"] is not None:
        payload["target_roles"] = _decode_json_string_list(row["target_roles_json"])

    return payload


def _row_to_interview_session(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None

    payload: dict[str, Any] = {
        "session_id": row["session_id"],
        "job_spec_id": row["job_spec_id"],
        "candidate_id": row["candidate_id"],
        "questions": _decode_json_list(row["questions_json"]),
        "scores": _decode_json_object(row["scores_json"]),
        "overall_score": row["overall_score"],
        "created_at": row["created_at"],
    }

    if row["mode"] is not None:
        payload["mode"] = row["mode"]
    if row["root_cause_tags_json"] is not None:
        payload["root_cause_tags"] = _decode_json_string_list(row["root_cause_tags_json"])
    if row["status"] is not None:
        payload["status"] = row["status"]
    if row["version"] is not None:
        payload["version"] = row["version"]

    return payload


def _row_to_feedback_report(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return _decode_json_object(str(row["payload_json"]))


def _row_to_negotiation_plan(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    payload = _decode_json_object(str(row["payload_json"]))
    row_keys = set(row.keys())

    if "version" in row_keys:
        row_version = row["version"]
        if isinstance(row_version, int):
            payload["version"] = row_version

    if "supersedes_negotiation_plan_id" in row_keys and row["supersedes_negotiation_plan_id"] is not None:
        payload["supersedes_negotiation_plan_id"] = str(row["supersedes_negotiation_plan_id"])

    return payload


def _row_to_trajectory_plan(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    payload = _decode_json_object(str(row["payload_json"]))
    row_keys = set(row.keys())

    if "version" in row_keys:
        row_version = row["version"]
        if isinstance(row_version, int):
            payload["version"] = row_version

    if "supersedes_trajectory_plan_id" in row_keys and row["supersedes_trajectory_plan_id"] is not None:
        payload["supersedes_trajectory_plan_id"] = str(row["supersedes_trajectory_plan_id"])

    return payload


def _decode_json_list(raw: str) -> list[Any]:
    try:
        decoded = json.loads(raw)
    except json.JSONDecodeError:
        return []
    return decoded if isinstance(decoded, list) else []


def _decode_json_object(raw: str) -> dict[str, Any]:
    try:
        decoded = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return decoded if isinstance(decoded, dict) else {}


def _decode_json_string_list(raw: str) -> list[str]:
    decoded = _decode_json_list(raw)
    return [value for value in decoded if isinstance(value, str)]


def _build_eval_run_lifecycle_event_id(*, eval_run_id: str, status: str) -> str:
    return f"evt_eval_run_{eval_run_id}_{status}"


def _build_eval_run_lifecycle_event_payload(
    *,
    eval_run_payload: dict[str, Any],
    lifecycle_status: str,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "eval_run_id": str(eval_run_payload.get("eval_run_id", "")),
        "suite": str(eval_run_payload.get("suite", "")),
        "status": lifecycle_status,
    }
    for field in ("created_at", "started_at", "completed_at"):
        value = eval_run_payload.get(field)
        if isinstance(value, str) and value.strip():
            payload[field] = value

    if lifecycle_status in {"succeeded", "failed"}:
        metrics = eval_run_payload.get("metrics")
        payload["metrics"] = metrics if isinstance(metrics, dict) else {}
        error_payload = eval_run_payload.get("error")
        if isinstance(error_payload, dict):
            payload["error"] = {
                "code": str(error_payload.get("code", "")),
                "message": str(error_payload.get("message", "")),
            }

    return payload


def _canonical_json(value: Any) -> str:
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False, sort_keys=True)
