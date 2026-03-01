from __future__ import annotations

import importlib.util
import json
import os
import re
import sys
import unicodedata
from datetime import datetime, timezone
from http import HTTPStatus
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote
from uuid import uuid4

from .repository import CandidateIngestionRecord, JobIngestionRecord, SQLiteJobIngestionRepository

SOURCE_TYPE_VALUES = {"url", "text", "document_ref"}
INTERVIEW_MODE_VALUES = {"mock_interview", "drill", "negotiation"}
ROOT_DIR = Path(__file__).resolve().parents[3]
JOB_EXTRACTION_PATH = ROOT_DIR / "services" / "job-extraction" / "worker.py"
TAXONOMY_PATH = ROOT_DIR / "services" / "taxonomy" / "normalizer.py"
SCHEMA_VALIDATOR_PATH = ROOT_DIR / "services" / "quality-eval" / "schema_validation" / "validator.py"
CANDIDATE_PROFILE_PARSER_PATH = ROOT_DIR / "services" / "candidate-profile" / "parser.py"
CANDIDATE_STORYBANK_PATH = ROOT_DIR / "services" / "candidate-profile" / "storybank.py"
INTERVIEW_PLANNER_PATH = ROOT_DIR / "services" / "interview-engine" / "planner.py"
INTERVIEW_FOLLOWUP_PATH = ROOT_DIR / "services" / "interview-engine" / "followup.py"
PROGRESS_AGGREGATOR_PATH = ROOT_DIR / "services" / "progress-tracking" / "aggregator.py"
TRAJECTORY_PLANNER_PATH = ROOT_DIR / "services" / "trajectory-planning" / "generator.py"
NEGOTIATION_CONTEXT_AGGREGATOR_PATH = ROOT_DIR / "services" / "negotiation-planning" / "aggregator.py"
NEGOTIATION_STRATEGY_GENERATOR_PATH = ROOT_DIR / "services" / "negotiation-planning" / "generator.py"
INTERVIEW_ROUTE_PREFIX = "/v1/interview-sessions/"
INTERVIEW_RESPONSES_SUFFIX = "/responses"
FEEDBACK_ROUTE_PREFIX = "/v1/feedback-reports/"
NEGOTIATION_ROUTE_PREFIX = "/v1/negotiation-plans/"
TRAJECTORY_ROUTE_PREFIX = "/v1/trajectory-plans/"
JOB_SPEC_ROUTE_PREFIX = "/v1/job-specs/"
JOB_SPEC_REVIEW_ROUTE_SUFFIX = "/review"
COMPETENCY_FIT_ROUTE = "/v1/competency-fits"
CANDIDATE_ROUTE_PREFIX = "/v1/candidates/"
CANDIDATE_PROFILE_SUFFIX = "/profile"
CANDIDATE_STORYBANK_SUFFIX = "/storybank"
CANDIDATE_PROGRESS_DASHBOARD_SUFFIX = "/progress-dashboard"
FOLLOWUP_OVERRIDE_CONFIDENCE_THRESHOLD = 0.80
IMMUTABLE_JOB_SPEC_PATCH_FIELDS = {"job_spec_id", "source", "version"}
MUTABLE_JOB_SPEC_PATCH_FIELDS = {
    "company",
    "role_title",
    "seniority_level",
    "location",
    "employment_type",
    "responsibilities",
    "requirements",
    "competency_weights",
    "evidence_spans",
    "extraction_confidence",
    "taxonomy_version",
}


def _load_module(module_name: str, module_path: Path):
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load module: {module_path}")

    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


_JOB_EXTRACTION_MODULE = _load_module("job_extraction_worker", JOB_EXTRACTION_PATH)
_TAXONOMY_MODULE = _load_module("taxonomy_normalizer", TAXONOMY_PATH)
_SCHEMA_VALIDATOR_MODULE = _load_module("core_schema_validator", SCHEMA_VALIDATOR_PATH)
_CANDIDATE_PROFILE_MODULE = _load_module("candidate_profile_parser", CANDIDATE_PROFILE_PARSER_PATH)
_CANDIDATE_STORYBANK_MODULE = _load_module("candidate_storybank_generator", CANDIDATE_STORYBANK_PATH)
_INTERVIEW_PLANNER_MODULE = _load_module("interview_question_planner", INTERVIEW_PLANNER_PATH)
_INTERVIEW_FOLLOWUP_MODULE = _load_module("interview_followup_selector", INTERVIEW_FOLLOWUP_PATH)
_PROGRESS_AGGREGATOR_MODULE = _load_module("progress_aggregator", PROGRESS_AGGREGATOR_PATH)
_TRAJECTORY_PLANNER_MODULE = _load_module("trajectory_planner", TRAJECTORY_PLANNER_PATH)
_NEGOTIATION_CONTEXT_AGGREGATOR_MODULE = _load_module(
    "negotiation_context_aggregator",
    NEGOTIATION_CONTEXT_AGGREGATOR_PATH,
)
_NEGOTIATION_STRATEGY_GENERATOR_MODULE = _load_module(
    "negotiation_strategy_generator",
    NEGOTIATION_STRATEGY_GENERATOR_PATH,
)


class JobIngestionAPI:
    def __init__(
        self,
        repository: SQLiteJobIngestionRepository,
        *,
        extraction_worker: Any,
        taxonomy_normalizer: Any,
        schema_validator: Any,
        candidate_profile_parser: Any,
        candidate_storybank_generator: Any,
        interview_question_planner: Any,
        interview_followup_selector: Any,
        progress_aggregator: Any,
        trajectory_planner: Any,
        negotiation_context_aggregator: Any,
        negotiation_strategy_generator: Any,
    ) -> None:
        self._repository = repository
        self._extraction_worker = extraction_worker
        self._taxonomy_normalizer = taxonomy_normalizer
        self._schema_validator = schema_validator
        self._candidate_profile_parser = candidate_profile_parser
        self._candidate_storybank_generator = candidate_storybank_generator
        self._interview_question_planner = interview_question_planner
        self._interview_followup_selector = interview_followup_selector
        self._progress_aggregator = progress_aggregator
        self._trajectory_planner = trajectory_planner
        self._negotiation_context_aggregator = negotiation_context_aggregator
        self._negotiation_strategy_generator = negotiation_strategy_generator

    def __call__(self, environ: dict[str, Any], start_response: Any) -> list[bytes]:
        method = str(environ.get("REQUEST_METHOD", "")).upper()
        path = str(environ.get("PATH_INFO", ""))
        request_id = _request_id(environ)

        if path == "/v1/job-ingestions":
            if method != "POST":
                return _json_response(
                    start_response,
                    HTTPStatus.METHOD_NOT_ALLOWED,
                    _error_envelope(request_id=request_id, code="method_not_allowed", message="Method not allowed", retryable=False),
                    headers=[("Allow", "POST")],
                )
            return self._handle_create(environ, start_response, request_id=request_id)

        if path.startswith("/v1/job-ingestions/"):
            ingestion_id = unquote(path[len("/v1/job-ingestions/") :])
            if not ingestion_id or "/" in ingestion_id:
                return _json_response(
                    start_response,
                    HTTPStatus.NOT_FOUND,
                    _error_envelope(request_id=request_id, code="not_found", message="Resource not found", retryable=False),
                )
            if method != "GET":
                return _json_response(
                    start_response,
                    HTTPStatus.METHOD_NOT_ALLOWED,
                    _error_envelope(request_id=request_id, code="method_not_allowed", message="Method not allowed", retryable=False),
                    headers=[("Allow", "GET")],
                )
            return self._handle_get(start_response, request_id=request_id, ingestion_id=ingestion_id)

        if path == "/v1/candidate-ingestions":
            if method != "POST":
                return _json_response(
                    start_response,
                    HTTPStatus.METHOD_NOT_ALLOWED,
                    _error_envelope(request_id=request_id, code="method_not_allowed", message="Method not allowed", retryable=False),
                    headers=[("Allow", "POST")],
                )
            return self._handle_create_candidate(environ, start_response, request_id=request_id)

        if path.startswith("/v1/candidate-ingestions/"):
            ingestion_id = unquote(path[len("/v1/candidate-ingestions/") :])
            if not ingestion_id or "/" in ingestion_id:
                return _json_response(
                    start_response,
                    HTTPStatus.NOT_FOUND,
                    _error_envelope(request_id=request_id, code="not_found", message="Resource not found", retryable=False),
                )
            if method != "GET":
                return _json_response(
                    start_response,
                    HTTPStatus.METHOD_NOT_ALLOWED,
                    _error_envelope(request_id=request_id, code="method_not_allowed", message="Method not allowed", retryable=False),
                    headers=[("Allow", "GET")],
                )
            return self._handle_get_candidate(start_response, request_id=request_id, ingestion_id=ingestion_id)

        if path == COMPETENCY_FIT_ROUTE:
            if method != "POST":
                return _json_response(
                    start_response,
                    HTTPStatus.METHOD_NOT_ALLOWED,
                    _error_envelope(request_id=request_id, code="method_not_allowed", message="Method not allowed", retryable=False),
                    headers=[("Allow", "POST")],
                )
            return self._handle_create_competency_fit(environ, start_response, request_id=request_id)

        if path == "/v1/interview-sessions":
            if method != "POST":
                return _json_response(
                    start_response,
                    HTTPStatus.METHOD_NOT_ALLOWED,
                    _error_envelope(request_id=request_id, code="method_not_allowed", message="Method not allowed", retryable=False),
                    headers=[("Allow", "POST")],
                )
            return self._handle_create_interview_session(environ, start_response, request_id=request_id)

        if path.startswith(INTERVIEW_ROUTE_PREFIX) and path.endswith(INTERVIEW_RESPONSES_SUFFIX):
            session_id = unquote(path[len(INTERVIEW_ROUTE_PREFIX) : -len(INTERVIEW_RESPONSES_SUFFIX)])
            if session_id.endswith("/"):
                session_id = session_id[:-1]
            if not session_id or "/" in session_id:
                return _json_response(
                    start_response,
                    HTTPStatus.NOT_FOUND,
                    _error_envelope(request_id=request_id, code="not_found", message="Resource not found", retryable=False),
                )
            if method != "POST":
                return _json_response(
                    start_response,
                    HTTPStatus.METHOD_NOT_ALLOWED,
                    _error_envelope(request_id=request_id, code="method_not_allowed", message="Method not allowed", retryable=False),
                    headers=[("Allow", "POST")],
                )
            return self._handle_append_interview_response(
                environ,
                start_response,
                request_id=request_id,
                session_id=session_id,
            )

        if path.startswith(INTERVIEW_ROUTE_PREFIX):
            session_id = unquote(path[len(INTERVIEW_ROUTE_PREFIX) :])
            if not session_id or "/" in session_id:
                return _json_response(
                    start_response,
                    HTTPStatus.NOT_FOUND,
                    _error_envelope(request_id=request_id, code="not_found", message="Resource not found", retryable=False),
                )
            if method != "GET":
                return _json_response(
                    start_response,
                    HTTPStatus.METHOD_NOT_ALLOWED,
                    _error_envelope(request_id=request_id, code="method_not_allowed", message="Method not allowed", retryable=False),
                    headers=[("Allow", "GET")],
                )
            return self._handle_get_interview_session(
                start_response,
                request_id=request_id,
                session_id=session_id,
            )

        if path == "/v1/feedback-reports":
            if method != "POST":
                return _json_response(
                    start_response,
                    HTTPStatus.METHOD_NOT_ALLOWED,
                    _error_envelope(request_id=request_id, code="method_not_allowed", message="Method not allowed", retryable=False),
                    headers=[("Allow", "POST")],
                )
            return self._handle_create_feedback_report(environ, start_response, request_id=request_id)

        if path.startswith(FEEDBACK_ROUTE_PREFIX):
            feedback_report_id = unquote(path[len(FEEDBACK_ROUTE_PREFIX) :])
            if not feedback_report_id or "/" in feedback_report_id:
                return _json_response(
                    start_response,
                    HTTPStatus.NOT_FOUND,
                    _error_envelope(request_id=request_id, code="not_found", message="Resource not found", retryable=False),
                )
            if method != "GET":
                return _json_response(
                    start_response,
                    HTTPStatus.METHOD_NOT_ALLOWED,
                    _error_envelope(request_id=request_id, code="method_not_allowed", message="Method not allowed", retryable=False),
                    headers=[("Allow", "GET")],
                )
            return self._handle_get_feedback_report(
                start_response,
                request_id=request_id,
                feedback_report_id=feedback_report_id,
            )

        if path == "/v1/negotiation-plans":
            if method != "POST":
                return _json_response(
                    start_response,
                    HTTPStatus.METHOD_NOT_ALLOWED,
                    _error_envelope(request_id=request_id, code="method_not_allowed", message="Method not allowed", retryable=False),
                    headers=[("Allow", "POST")],
                )
            return self._handle_create_negotiation_plan(environ, start_response, request_id=request_id)

        if path.startswith(NEGOTIATION_ROUTE_PREFIX):
            negotiation_plan_id = unquote(path[len(NEGOTIATION_ROUTE_PREFIX) :])
            if not negotiation_plan_id or "/" in negotiation_plan_id:
                return _json_response(
                    start_response,
                    HTTPStatus.NOT_FOUND,
                    _error_envelope(request_id=request_id, code="not_found", message="Resource not found", retryable=False),
                )
            if method != "GET":
                return _json_response(
                    start_response,
                    HTTPStatus.METHOD_NOT_ALLOWED,
                    _error_envelope(request_id=request_id, code="method_not_allowed", message="Method not allowed", retryable=False),
                    headers=[("Allow", "GET")],
                )
            return self._handle_get_negotiation_plan(
                start_response,
                request_id=request_id,
                negotiation_plan_id=negotiation_plan_id,
            )

        if path == "/v1/trajectory-plans":
            if method != "POST":
                return _json_response(
                    start_response,
                    HTTPStatus.METHOD_NOT_ALLOWED,
                    _error_envelope(request_id=request_id, code="method_not_allowed", message="Method not allowed", retryable=False),
                    headers=[("Allow", "POST")],
                )
            return self._handle_create_trajectory_plan(environ, start_response, request_id=request_id)

        if path.startswith(TRAJECTORY_ROUTE_PREFIX):
            trajectory_plan_id = unquote(path[len(TRAJECTORY_ROUTE_PREFIX) :])
            if not trajectory_plan_id or "/" in trajectory_plan_id:
                return _json_response(
                    start_response,
                    HTTPStatus.NOT_FOUND,
                    _error_envelope(request_id=request_id, code="not_found", message="Resource not found", retryable=False),
                )
            if method != "GET":
                return _json_response(
                    start_response,
                    HTTPStatus.METHOD_NOT_ALLOWED,
                    _error_envelope(request_id=request_id, code="method_not_allowed", message="Method not allowed", retryable=False),
                    headers=[("Allow", "GET")],
                )
            return self._handle_get_trajectory_plan(
                start_response,
                request_id=request_id,
                trajectory_plan_id=trajectory_plan_id,
            )

        if path.startswith(CANDIDATE_ROUTE_PREFIX) and path.endswith(CANDIDATE_PROFILE_SUFFIX):
            candidate_id = unquote(path[len(CANDIDATE_ROUTE_PREFIX) : -len(CANDIDATE_PROFILE_SUFFIX)])
            if candidate_id.endswith("/"):
                candidate_id = candidate_id[:-1]
            if not candidate_id or "/" in candidate_id:
                return _json_response(
                    start_response,
                    HTTPStatus.NOT_FOUND,
                    _error_envelope(request_id=request_id, code="not_found", message="Resource not found", retryable=False),
                )
            if method != "GET":
                return _json_response(
                    start_response,
                    HTTPStatus.METHOD_NOT_ALLOWED,
                    _error_envelope(request_id=request_id, code="method_not_allowed", message="Method not allowed", retryable=False),
                    headers=[("Allow", "GET")],
                )
            return self._handle_get_candidate_profile(
                start_response,
                request_id=request_id,
                candidate_id=candidate_id,
            )

        if path.startswith(CANDIDATE_ROUTE_PREFIX) and path.endswith(CANDIDATE_STORYBANK_SUFFIX):
            candidate_id = unquote(path[len(CANDIDATE_ROUTE_PREFIX) : -len(CANDIDATE_STORYBANK_SUFFIX)])
            if candidate_id.endswith("/"):
                candidate_id = candidate_id[:-1]
            if not candidate_id or "/" in candidate_id:
                return _json_response(
                    start_response,
                    HTTPStatus.NOT_FOUND,
                    _error_envelope(request_id=request_id, code="not_found", message="Resource not found", retryable=False),
                )
            if method != "GET":
                return _json_response(
                    start_response,
                    HTTPStatus.METHOD_NOT_ALLOWED,
                    _error_envelope(request_id=request_id, code="method_not_allowed", message="Method not allowed", retryable=False),
                    headers=[("Allow", "GET")],
                )
            return self._handle_get_candidate_storybank(
                environ,
                start_response,
                request_id=request_id,
                candidate_id=candidate_id,
            )

        if path.startswith(CANDIDATE_ROUTE_PREFIX) and path.endswith(CANDIDATE_PROGRESS_DASHBOARD_SUFFIX):
            candidate_id = unquote(path[len(CANDIDATE_ROUTE_PREFIX) : -len(CANDIDATE_PROGRESS_DASHBOARD_SUFFIX)])
            if candidate_id.endswith("/"):
                candidate_id = candidate_id[:-1]
            if not candidate_id or "/" in candidate_id:
                return _json_response(
                    start_response,
                    HTTPStatus.NOT_FOUND,
                    _error_envelope(request_id=request_id, code="not_found", message="Resource not found", retryable=False),
                )
            if method != "GET":
                return _json_response(
                    start_response,
                    HTTPStatus.METHOD_NOT_ALLOWED,
                    _error_envelope(request_id=request_id, code="method_not_allowed", message="Method not allowed", retryable=False),
                    headers=[("Allow", "GET")],
                )
            return self._handle_get_candidate_progress_dashboard(
                environ,
                start_response,
                request_id=request_id,
                candidate_id=candidate_id,
            )

        if path.startswith(JOB_SPEC_ROUTE_PREFIX) and path.endswith(JOB_SPEC_REVIEW_ROUTE_SUFFIX):
            job_spec_id = unquote(path[len(JOB_SPEC_ROUTE_PREFIX) : -len(JOB_SPEC_REVIEW_ROUTE_SUFFIX)])
            if job_spec_id.endswith("/"):
                job_spec_id = job_spec_id[:-1]
            if not job_spec_id or "/" in job_spec_id:
                return _json_response(
                    start_response,
                    HTTPStatus.NOT_FOUND,
                    _error_envelope(request_id=request_id, code="not_found", message="Resource not found", retryable=False),
                )
            if method != "PATCH":
                return _json_response(
                    start_response,
                    HTTPStatus.METHOD_NOT_ALLOWED,
                    _error_envelope(request_id=request_id, code="method_not_allowed", message="Method not allowed", retryable=False),
                    headers=[("Allow", "PATCH")],
                )
            return self._handle_patch_job_spec_review(
                environ,
                start_response,
                request_id=request_id,
                job_spec_id=job_spec_id,
            )

        if path.startswith(JOB_SPEC_ROUTE_PREFIX):
            job_spec_id = unquote(path[len(JOB_SPEC_ROUTE_PREFIX) :])
            if not job_spec_id or "/" in job_spec_id:
                return _json_response(
                    start_response,
                    HTTPStatus.NOT_FOUND,
                    _error_envelope(request_id=request_id, code="not_found", message="Resource not found", retryable=False),
                )
            if method != "GET":
                return _json_response(
                    start_response,
                    HTTPStatus.METHOD_NOT_ALLOWED,
                    _error_envelope(request_id=request_id, code="method_not_allowed", message="Method not allowed", retryable=False),
                    headers=[("Allow", "GET")],
                )
            return self._handle_get_job_spec(start_response, request_id=request_id, job_spec_id=job_spec_id)

        return _json_response(
            start_response,
            HTTPStatus.NOT_FOUND,
            _error_envelope(request_id=request_id, code="not_found", message="Resource not found", retryable=False),
        )

    def _handle_create(self, environ: dict[str, Any], start_response: Any, *, request_id: str) -> list[bytes]:
        idempotency_key = str(environ.get("HTTP_IDEMPOTENCY_KEY", "")).strip()
        if not idempotency_key:
            return _json_response(
                start_response,
                HTTPStatus.BAD_REQUEST,
                _error_envelope(
                    request_id=request_id,
                    code="invalid_request",
                    message="Idempotency-Key header is required",
                    retryable=False,
                    details=[{"field": "Idempotency-Key", "reason": "required"}],
                ),
            )

        payload, payload_error = _parse_json_payload(environ)
        if payload_error:
            return _json_response(
                start_response,
                HTTPStatus.BAD_REQUEST,
                _error_envelope(
                    request_id=request_id,
                    code="invalid_request",
                    message=payload_error,
                    retryable=False,
                ),
            )

        validation_errors = _validate_create_payload(payload)
        if validation_errors:
            return _json_response(
                start_response,
                HTTPStatus.BAD_REQUEST,
                _error_envelope(
                    request_id=request_id,
                    code="invalid_request",
                    message="Request body validation failed",
                    retryable=False,
                    details=validation_errors,
                ),
            )

        source_type = str(payload["source_type"])
        source_value = str(payload["source_value"])
        target_locale = str(payload.get("target_locale") or "en-US")

        create_result = self._repository.create_or_get(
            idempotency_key=idempotency_key,
            source_type=source_type,
            source_value=source_value,
            target_locale=target_locale,
        )

        existing_record = create_result.record
        if not create_result.created and (
            existing_record.source_type != source_type
            or existing_record.source_value != source_value
            or existing_record.target_locale != target_locale
        ):
            return _json_response(
                start_response,
                HTTPStatus.CONFLICT,
                _error_envelope(
                    request_id=request_id,
                    code="idempotency_key_conflict",
                    message="Idempotency-Key is already associated with a different request",
                    retryable=False,
                ),
            )

        if source_type in {"text", "url"} and not existing_record.result_job_spec_id:
            job_spec_payload = self._build_job_spec_payload(existing_record)
            validation = self._schema_validator.validate("JobSpec", job_spec_payload)
            if not validation.is_valid:
                issue_summary = [{"path": issue.path, "message": issue.message} for issue in validation.issues]
                return _json_response(
                    start_response,
                    HTTPStatus.UNPROCESSABLE_ENTITY,
                    _error_envelope(
                        request_id=request_id,
                        code="invalid_job_spec",
                        message="Generated JobSpec failed schema validation",
                        retryable=False,
                        details=issue_summary,
                    ),
                )

            self._repository.persist_job_spec(ingestion_id=existing_record.ingestion_id, job_spec=job_spec_payload)
            refreshed = self._repository.get_by_id(existing_record.ingestion_id)
            if refreshed is not None:
                existing_record = refreshed

        return _json_response(
            start_response,
            HTTPStatus.ACCEPTED,
            _success_envelope(
                request_id=request_id,
                data={
                    "ingestion_id": existing_record.ingestion_id,
                    "status": "queued",
                },
            ),
        )

    def _handle_get(self, start_response: Any, *, request_id: str, ingestion_id: str) -> list[bytes]:
        record = self._repository.get_by_id(ingestion_id)
        if record is None:
            return _json_response(
                start_response,
                HTTPStatus.NOT_FOUND,
                _error_envelope(
                    request_id=request_id,
                    code="not_found",
                    message="Job ingestion not found",
                    retryable=False,
                ),
            )

        return _json_response(
            start_response,
            HTTPStatus.OK,
            _success_envelope(
                request_id=request_id,
                data=_status_payload(record),
            ),
        )

    def _handle_create_candidate(self, environ: dict[str, Any], start_response: Any, *, request_id: str) -> list[bytes]:
        idempotency_key = str(environ.get("HTTP_IDEMPOTENCY_KEY", "")).strip()
        if not idempotency_key:
            return _json_response(
                start_response,
                HTTPStatus.BAD_REQUEST,
                _error_envelope(
                    request_id=request_id,
                    code="invalid_request",
                    message="Idempotency-Key header is required",
                    retryable=False,
                    details=[{"field": "Idempotency-Key", "reason": "required"}],
                ),
            )

        payload, payload_error = _parse_json_payload(environ)
        if payload_error:
            return _json_response(
                start_response,
                HTTPStatus.BAD_REQUEST,
                _error_envelope(
                    request_id=request_id,
                    code="invalid_request",
                    message=payload_error,
                    retryable=False,
                ),
            )

        validation_errors = _validate_create_candidate_payload(payload)
        if validation_errors:
            return _json_response(
                start_response,
                HTTPStatus.BAD_REQUEST,
                _error_envelope(
                    request_id=request_id,
                    code="invalid_request",
                    message="Request body validation failed",
                    retryable=False,
                    details=validation_errors,
                ),
            )

        candidate_id = str(payload["candidate_id"]) if payload.get("candidate_id") is not None else None
        cv_text = str(payload["cv_text"]) if payload.get("cv_text") is not None else None
        cv_document_ref = str(payload["cv_document_ref"]) if payload.get("cv_document_ref") is not None else None
        story_notes = [str(item) for item in payload["story_notes"]] if isinstance(payload.get("story_notes"), list) else None
        target_roles = [str(item) for item in payload["target_roles"]] if isinstance(payload.get("target_roles"), list) else None
        target_locale = str(payload.get("target_locale") or "en-US")

        create_result = self._repository.create_or_get_candidate(
            idempotency_key=idempotency_key,
            candidate_id=candidate_id,
            cv_text=cv_text,
            cv_document_ref=cv_document_ref,
            story_notes=story_notes,
            target_roles=target_roles,
            target_locale=target_locale,
        )

        existing_record = create_result.record
        if not create_result.created and (
            existing_record.candidate_id != candidate_id
            or existing_record.cv_text != cv_text
            or existing_record.cv_document_ref != cv_document_ref
            or existing_record.story_notes != story_notes
            or existing_record.target_roles != target_roles
            or existing_record.target_locale != target_locale
        ):
            return _json_response(
                start_response,
                HTTPStatus.CONFLICT,
                _error_envelope(
                    request_id=request_id,
                    code="idempotency_key_conflict",
                    message="Idempotency-Key is already associated with a different request",
                    retryable=False,
                ),
            )

        if not existing_record.result_candidate_id:
            candidate_profile_payload = self._build_candidate_profile_payload(existing_record)
            storybank_entries = self._build_candidate_storybank_payload(
                candidate_profile_payload=candidate_profile_payload,
                record=existing_record,
            )

            candidate_profile_with_storybank = dict(candidate_profile_payload)
            if storybank_entries:
                candidate_profile_with_storybank["storybank"] = storybank_entries

            validation = self._schema_validator.validate("CandidateProfile", candidate_profile_with_storybank)
            if not validation.is_valid:
                issue_summary = [{"path": issue.path, "message": issue.message} for issue in validation.issues]
                return _json_response(
                    start_response,
                    HTTPStatus.UNPROCESSABLE_ENTITY,
                    _error_envelope(
                        request_id=request_id,
                        code="invalid_candidate_profile",
                        message="Generated CandidateProfile failed schema validation",
                        retryable=False,
                        details=issue_summary,
                    ),
                )

            self._repository.persist_candidate_profile(
                ingestion_id=existing_record.ingestion_id,
                candidate_profile=candidate_profile_payload,
            )
            self._repository.replace_candidate_storybank(
                candidate_id=str(candidate_profile_payload["candidate_id"]),
                stories=storybank_entries,
            )
            refreshed = self._repository.get_candidate_by_id(existing_record.ingestion_id)
            if refreshed is not None:
                existing_record = refreshed

        return _json_response(
            start_response,
            HTTPStatus.ACCEPTED,
            _success_envelope(
                request_id=request_id,
                data={
                    "ingestion_id": existing_record.ingestion_id,
                    "status": "queued",
                },
            ),
        )

    def _handle_get_candidate(self, start_response: Any, *, request_id: str, ingestion_id: str) -> list[bytes]:
        record = self._repository.get_candidate_by_id(ingestion_id)
        if record is None:
            return _json_response(
                start_response,
                HTTPStatus.NOT_FOUND,
                _error_envelope(
                    request_id=request_id,
                    code="not_found",
                    message="Candidate ingestion not found",
                    retryable=False,
                ),
            )

        return _json_response(
            start_response,
            HTTPStatus.OK,
            _success_envelope(
                request_id=request_id,
                data=_candidate_status_payload(record),
            ),
        )

    def _handle_create_competency_fit(
        self,
        environ: dict[str, Any],
        start_response: Any,
        *,
        request_id: str,
    ) -> list[bytes]:
        payload, payload_error = _parse_json_payload(environ)
        if payload_error:
            return _json_response(
                start_response,
                HTTPStatus.BAD_REQUEST,
                _error_envelope(
                    request_id=request_id,
                    code="invalid_request",
                    message=payload_error,
                    retryable=False,
                ),
            )

        validation_errors = _validate_create_competency_fit_payload(payload)
        if validation_errors:
            return _json_response(
                start_response,
                HTTPStatus.BAD_REQUEST,
                _error_envelope(
                    request_id=request_id,
                    code="invalid_request",
                    message="Request body validation failed",
                    retryable=False,
                    details=validation_errors,
                ),
            )

        job_spec_id = str(payload["job_spec_id"]).strip()
        candidate_id = str(payload["candidate_id"]).strip()

        job_spec = self._repository.get_job_spec_by_id(job_spec_id)
        if job_spec is None:
            return _json_response(
                start_response,
                HTTPStatus.NOT_FOUND,
                _error_envelope(
                    request_id=request_id,
                    code="not_found",
                    message="Job spec not found",
                    retryable=False,
                ),
            )

        candidate_profile = self._repository.get_candidate_profile_by_id(candidate_id)
        if candidate_profile is None:
            return _json_response(
                start_response,
                HTTPStatus.NOT_FOUND,
                _error_envelope(
                    request_id=request_id,
                    code="not_found",
                    message="Candidate profile not found",
                    retryable=False,
                ),
            )

        fit_payload = self._build_competency_fit_payload(
            job_spec_id=job_spec_id,
            candidate_id=candidate_id,
            job_spec=job_spec,
            candidate_profile=candidate_profile,
        )

        return _json_response(
            start_response,
            HTTPStatus.OK,
            _success_envelope(request_id=request_id, data=fit_payload),
        )

    def _handle_get_candidate_profile(self, start_response: Any, *, request_id: str, candidate_id: str) -> list[bytes]:
        profile = self._repository.get_candidate_profile_by_id(candidate_id)
        if profile is None:
            return _json_response(
                start_response,
                HTTPStatus.NOT_FOUND,
                _error_envelope(
                    request_id=request_id,
                    code="not_found",
                    message="Candidate profile not found",
                    retryable=False,
                ),
            )

        storybank_items = self._repository.get_candidate_storybank(candidate_id=candidate_id)
        if storybank_items:
            profile = dict(profile)
            profile["storybank"] = storybank_items

        return _json_response(
            start_response,
            HTTPStatus.OK,
            _success_envelope(request_id=request_id, data=profile),
        )

    def _handle_get_candidate_storybank(
        self,
        environ: dict[str, Any],
        start_response: Any,
        *,
        request_id: str,
        candidate_id: str,
    ) -> list[bytes]:
        profile = self._repository.get_candidate_profile_by_id(candidate_id)
        if profile is None:
            return _json_response(
                start_response,
                HTTPStatus.NOT_FOUND,
                _error_envelope(
                    request_id=request_id,
                    code="not_found",
                    message="Candidate profile not found",
                    retryable=False,
                ),
            )

        query, query_errors = _parse_storybank_query(environ)
        if query_errors:
            return _json_response(
                start_response,
                HTTPStatus.BAD_REQUEST,
                _error_envelope(
                    request_id=request_id,
                    code="invalid_request",
                    message="Query parameter validation failed",
                    retryable=False,
                    details=query_errors,
                ),
            )

        items, next_cursor = self._repository.list_candidate_storybank(
            candidate_id=candidate_id,
            min_quality=query["min_quality"],
            competency=query["competency"],
            limit=query["limit"],
            cursor_offset=query["cursor_offset"],
        )

        return _json_response(
            start_response,
            HTTPStatus.OK,
            _success_envelope(
                request_id=request_id,
                data={
                    "items": items,
                    "next_cursor": next_cursor,
                },
            ),
        )

    def _handle_get_candidate_progress_dashboard(
        self,
        environ: dict[str, Any],
        start_response: Any,
        *,
        request_id: str,
        candidate_id: str,
    ) -> list[bytes]:
        candidate_profile = self._repository.get_candidate_profile_by_id(candidate_id)
        if candidate_profile is None:
            return _json_response(
                start_response,
                HTTPStatus.NOT_FOUND,
                _error_envelope(
                    request_id=request_id,
                    code="not_found",
                    message="Candidate profile not found",
                    retryable=False,
                ),
            )

        query, query_errors = _parse_candidate_progress_dashboard_query(environ)
        if query_errors:
            return _json_response(
                start_response,
                HTTPStatus.BAD_REQUEST,
                _error_envelope(
                    request_id=request_id,
                    code="invalid_request",
                    message="Query parameter validation failed",
                    retryable=False,
                    details=query_errors,
                ),
            )

        interview_history = self._repository.list_interview_sessions_for_candidate(candidate_id=candidate_id)
        feedback_history = self._repository.list_feedback_reports_for_candidate(candidate_id=candidate_id)
        progress_summary = self._progress_aggregator.aggregate(
            interview_sessions=interview_history,
            feedback_reports=feedback_history,
        )
        latest_trajectory_plan = self._repository.get_latest_trajectory_plan_for_candidate(
            candidate_id=candidate_id,
            target_role=query["target_role"],
        )
        dashboard_payload = self._build_candidate_progress_dashboard_payload(
            candidate_id=candidate_id,
            progress_summary=progress_summary,
            latest_trajectory_plan=latest_trajectory_plan,
        )

        validation = self._schema_validator.validate("CandidateProgressDashboard", dashboard_payload)
        if not validation.is_valid:
            issue_summary = [{"path": issue.path, "message": issue.message} for issue in validation.issues]
            return _json_response(
                start_response,
                HTTPStatus.UNPROCESSABLE_ENTITY,
                _error_envelope(
                    request_id=request_id,
                    code="invalid_candidate_progress_dashboard",
                    message="Generated candidate progress dashboard failed schema validation",
                    retryable=False,
                    details=issue_summary,
                ),
            )

        return _json_response(
            start_response,
            HTTPStatus.OK,
            _success_envelope(request_id=request_id, data=dashboard_payload),
        )

    def _handle_create_interview_session(
        self,
        environ: dict[str, Any],
        start_response: Any,
        *,
        request_id: str,
    ) -> list[bytes]:
        payload, payload_error = _parse_json_payload(environ)
        if payload_error:
            return _json_response(
                start_response,
                HTTPStatus.BAD_REQUEST,
                _error_envelope(
                    request_id=request_id,
                    code="invalid_request",
                    message=payload_error,
                    retryable=False,
                ),
            )

        validation_errors = _validate_create_interview_session_payload(payload)
        if validation_errors:
            return _json_response(
                start_response,
                HTTPStatus.BAD_REQUEST,
                _error_envelope(
                    request_id=request_id,
                    code="invalid_request",
                    message="Request body validation failed",
                    retryable=False,
                    details=validation_errors,
                ),
            )

        job_spec_id = str(payload["job_spec_id"])
        candidate_id = str(payload["candidate_id"])
        mode = str(payload.get("mode") or "mock_interview")

        job_spec = self._repository.get_job_spec_by_id(job_spec_id)
        if job_spec is None:
            return _json_response(
                start_response,
                HTTPStatus.NOT_FOUND,
                _error_envelope(
                    request_id=request_id,
                    code="not_found",
                    message="Job spec not found",
                    retryable=False,
                ),
            )

        candidate_profile = self._repository.get_candidate_profile_by_id(candidate_id)
        if candidate_profile is None:
            return _json_response(
                start_response,
                HTTPStatus.NOT_FOUND,
                _error_envelope(
                    request_id=request_id,
                    code="not_found",
                    message="Candidate profile not found",
                    retryable=False,
                ),
            )

        interview_session_payload = self._build_interview_session_payload(
            job_spec_id=job_spec_id,
            candidate_id=candidate_id,
            mode=mode,
            job_spec=job_spec,
            candidate_profile=candidate_profile,
        )
        validation = self._schema_validator.validate("InterviewSession", interview_session_payload)
        if not validation.is_valid:
            issue_summary = [{"path": issue.path, "message": issue.message} for issue in validation.issues]
            return _json_response(
                start_response,
                HTTPStatus.UNPROCESSABLE_ENTITY,
                _error_envelope(
                    request_id=request_id,
                    code="invalid_interview_session",
                    message="Generated InterviewSession failed schema validation",
                    retryable=False,
                    details=issue_summary,
                ),
            )

        try:
            self._repository.create_interview_session(interview_session=interview_session_payload)
        except Exception:
            return _json_response(
                start_response,
                HTTPStatus.INTERNAL_SERVER_ERROR,
                _error_envelope(
                    request_id=request_id,
                    code="internal_error",
                    message="Interview session could not be persisted",
                    retryable=True,
                ),
            )

        return _json_response(
            start_response,
            HTTPStatus.CREATED,
            _success_envelope(request_id=request_id, data=interview_session_payload),
        )

    def _handle_get_interview_session(
        self,
        start_response: Any,
        *,
        request_id: str,
        session_id: str,
    ) -> list[bytes]:
        payload = self._repository.get_interview_session_by_id(session_id)
        if payload is None:
            return _json_response(
                start_response,
                HTTPStatus.NOT_FOUND,
                _error_envelope(
                    request_id=request_id,
                    code="not_found",
                    message="Interview session not found",
                    retryable=False,
                ),
            )

        return _json_response(
            start_response,
            HTTPStatus.OK,
            _success_envelope(request_id=request_id, data=payload),
        )

    def _handle_create_feedback_report(
        self,
        environ: dict[str, Any],
        start_response: Any,
        *,
        request_id: str,
    ) -> list[bytes]:
        idempotency_key = str(environ.get("HTTP_IDEMPOTENCY_KEY", "")).strip()
        if not idempotency_key:
            return _json_response(
                start_response,
                HTTPStatus.BAD_REQUEST,
                _error_envelope(
                    request_id=request_id,
                    code="invalid_request",
                    message="Idempotency-Key header is required",
                    retryable=False,
                    details=[{"field": "Idempotency-Key", "reason": "required"}],
                ),
            )

        payload, payload_error = _parse_json_payload(environ)
        if payload_error:
            return _json_response(
                start_response,
                HTTPStatus.BAD_REQUEST,
                _error_envelope(
                    request_id=request_id,
                    code="invalid_request",
                    message=payload_error,
                    retryable=False,
                ),
            )

        validation_errors = _validate_create_feedback_report_payload(payload)
        if validation_errors:
            return _json_response(
                start_response,
                HTTPStatus.BAD_REQUEST,
                _error_envelope(
                    request_id=request_id,
                    code="invalid_request",
                    message="Request body validation failed",
                    retryable=False,
                    details=validation_errors,
                ),
            )

        session_id = str(payload["session_id"])
        session = self._repository.get_interview_session_by_id(session_id)
        if session is None:
            return _json_response(
                start_response,
                HTTPStatus.NOT_FOUND,
                _error_envelope(
                    request_id=request_id,
                    code="not_found",
                    message="Interview session not found",
                    retryable=False,
                ),
            )

        feedback_report_payload = self._build_feedback_report_payload(session)
        validation = self._schema_validator.validate("FeedbackReport", feedback_report_payload)
        if not validation.is_valid:
            issue_summary = [{"path": issue.path, "message": issue.message} for issue in validation.issues]
            return _json_response(
                start_response,
                HTTPStatus.UNPROCESSABLE_ENTITY,
                _error_envelope(
                    request_id=request_id,
                    code="invalid_feedback_report",
                    message="Generated FeedbackReport failed schema validation",
                    retryable=False,
                    details=issue_summary,
                ),
            )

        create_result = self._repository.create_or_get_feedback_report(
            idempotency_key=idempotency_key,
            request_payload=payload,
            feedback_report=feedback_report_payload,
        )
        if create_result.status == "session_not_found":
            return _json_response(
                start_response,
                HTTPStatus.NOT_FOUND,
                _error_envelope(
                    request_id=request_id,
                    code="not_found",
                    message="Interview session not found",
                    retryable=False,
                ),
            )
        if create_result.status == "idempotency_conflict":
            return _json_response(
                start_response,
                HTTPStatus.CONFLICT,
                _error_envelope(
                    request_id=request_id,
                    code="idempotency_key_conflict",
                    message="Idempotency-Key is already associated with a different request",
                    retryable=False,
                ),
            )
        if create_result.status == "version_conflict":
            details: list[dict[str, str]] = []
            if create_result.current_version is not None:
                details.append(
                    {
                        "field": "expected_version",
                        "reason": f"current version is {create_result.current_version}",
                    }
                )
            return _json_response(
                start_response,
                HTTPStatus.CONFLICT,
                _error_envelope(
                    request_id=request_id,
                    code="version_conflict",
                    message="expected_version does not match current feedback report version",
                    retryable=False,
                    details=details or None,
                ),
            )

        if create_result.report is None:
            return _json_response(
                start_response,
                HTTPStatus.INTERNAL_SERVER_ERROR,
                _error_envelope(
                    request_id=request_id,
                    code="internal_error",
                    message="Feedback report could not be persisted",
                    retryable=True,
                ),
            )

        return _json_response(
            start_response,
            HTTPStatus.CREATED,
            _success_envelope(request_id=request_id, data=create_result.report),
        )

    def _handle_get_feedback_report(
        self,
        start_response: Any,
        *,
        request_id: str,
        feedback_report_id: str,
    ) -> list[bytes]:
        payload = self._repository.get_feedback_report_by_id(feedback_report_id)
        if payload is None:
            return _json_response(
                start_response,
                HTTPStatus.NOT_FOUND,
                _error_envelope(
                    request_id=request_id,
                    code="not_found",
                    message="Feedback report not found",
                    retryable=False,
                ),
            )

        return _json_response(
            start_response,
            HTTPStatus.OK,
            _success_envelope(request_id=request_id, data=payload),
        )

    def _handle_create_negotiation_plan(
        self,
        environ: dict[str, Any],
        start_response: Any,
        *,
        request_id: str,
    ) -> list[bytes]:
        idempotency_key = str(environ.get("HTTP_IDEMPOTENCY_KEY", "")).strip()
        if not idempotency_key:
            return _json_response(
                start_response,
                HTTPStatus.BAD_REQUEST,
                _error_envelope(
                    request_id=request_id,
                    code="invalid_request",
                    message="Idempotency-Key header is required",
                    retryable=False,
                    details=[{"field": "Idempotency-Key", "reason": "required"}],
                ),
            )

        payload, payload_error = _parse_json_payload(environ)
        if payload_error:
            return _json_response(
                start_response,
                HTTPStatus.BAD_REQUEST,
                _error_envelope(
                    request_id=request_id,
                    code="invalid_request",
                    message=payload_error,
                    retryable=False,
                ),
            )

        validation_errors = _validate_create_negotiation_plan_payload(payload)
        if validation_errors:
            return _json_response(
                start_response,
                HTTPStatus.BAD_REQUEST,
                _error_envelope(
                    request_id=request_id,
                    code="invalid_request",
                    message="Request body validation failed",
                    retryable=False,
                    details=validation_errors,
                ),
            )

        candidate_id = str(payload["candidate_id"])
        target_role = str(payload["target_role"])
        candidate_profile = self._repository.get_candidate_profile_by_id(candidate_id)
        if candidate_profile is None:
            return _json_response(
                start_response,
                HTTPStatus.NOT_FOUND,
                _error_envelope(
                    request_id=request_id,
                    code="not_found",
                    message="Candidate profile not found",
                    retryable=False,
                ),
            )

        interview_history = self._repository.list_interview_sessions_for_candidate(candidate_id=candidate_id)
        feedback_history = self._repository.list_feedback_reports_for_candidate(candidate_id=candidate_id)
        latest_trajectory_plan = self._repository.get_latest_trajectory_plan_for_candidate(
            candidate_id=candidate_id,
            target_role=target_role,
        )

        negotiation_plan_payload = self._build_negotiation_plan_payload(
            candidate_id=candidate_id,
            candidate_profile=candidate_profile,
            target_role=target_role,
            request_payload=payload,
            interview_history=interview_history,
            feedback_history=feedback_history,
            latest_trajectory_plan=latest_trajectory_plan,
        )
        validation = self._schema_validator.validate("NegotiationPlan", negotiation_plan_payload)
        if not validation.is_valid:
            issue_summary = [{"path": issue.path, "message": issue.message} for issue in validation.issues]
            return _json_response(
                start_response,
                HTTPStatus.UNPROCESSABLE_ENTITY,
                _error_envelope(
                    request_id=request_id,
                    code="invalid_negotiation_plan",
                    message="Generated NegotiationPlan failed schema validation",
                    retryable=False,
                    details=issue_summary,
                ),
            )

        create_result = self._repository.create_or_get_negotiation_plan(
            idempotency_key=idempotency_key,
            request_payload=payload,
            negotiation_plan=negotiation_plan_payload,
        )
        if create_result.status == "candidate_not_found":
            return _json_response(
                start_response,
                HTTPStatus.NOT_FOUND,
                _error_envelope(
                    request_id=request_id,
                    code="not_found",
                    message="Candidate profile not found",
                    retryable=False,
                ),
            )
        if create_result.status == "idempotency_conflict":
            return _json_response(
                start_response,
                HTTPStatus.CONFLICT,
                _error_envelope(
                    request_id=request_id,
                    code="idempotency_key_conflict",
                    message="Idempotency-Key is already associated with a different request",
                    retryable=False,
                ),
            )
        if create_result.plan is None:
            return _json_response(
                start_response,
                HTTPStatus.INTERNAL_SERVER_ERROR,
                _error_envelope(
                    request_id=request_id,
                    code="internal_error",
                    message="Negotiation plan could not be persisted",
                    retryable=True,
                ),
            )

        return _json_response(
            start_response,
            HTTPStatus.CREATED,
            _success_envelope(request_id=request_id, data=create_result.plan),
        )

    def _handle_get_negotiation_plan(
        self,
        start_response: Any,
        *,
        request_id: str,
        negotiation_plan_id: str,
    ) -> list[bytes]:
        payload = self._repository.get_negotiation_plan_by_id(negotiation_plan_id)
        if payload is None:
            return _json_response(
                start_response,
                HTTPStatus.NOT_FOUND,
                _error_envelope(
                    request_id=request_id,
                    code="not_found",
                    message="Negotiation plan not found",
                    retryable=False,
                ),
            )

        return _json_response(
            start_response,
            HTTPStatus.OK,
            _success_envelope(request_id=request_id, data=payload),
        )

    def _handle_create_trajectory_plan(
        self,
        environ: dict[str, Any],
        start_response: Any,
        *,
        request_id: str,
    ) -> list[bytes]:
        idempotency_key = str(environ.get("HTTP_IDEMPOTENCY_KEY", "")).strip()
        if not idempotency_key:
            return _json_response(
                start_response,
                HTTPStatus.BAD_REQUEST,
                _error_envelope(
                    request_id=request_id,
                    code="invalid_request",
                    message="Idempotency-Key header is required",
                    retryable=False,
                    details=[{"field": "Idempotency-Key", "reason": "required"}],
                ),
            )

        payload, payload_error = _parse_json_payload(environ)
        if payload_error:
            return _json_response(
                start_response,
                HTTPStatus.BAD_REQUEST,
                _error_envelope(
                    request_id=request_id,
                    code="invalid_request",
                    message=payload_error,
                    retryable=False,
                ),
            )

        validation_errors = _validate_create_trajectory_plan_payload(payload)
        if validation_errors:
            return _json_response(
                start_response,
                HTTPStatus.BAD_REQUEST,
                _error_envelope(
                    request_id=request_id,
                    code="invalid_request",
                    message="Request body validation failed",
                    retryable=False,
                    details=validation_errors,
                ),
            )

        candidate_id = str(payload["candidate_id"])
        target_role = str(payload["target_role"])
        requested_horizon_months = payload.get("horizon_months")
        resolved_horizon_months = requested_horizon_months if isinstance(requested_horizon_months, int) else None

        candidate_profile = self._repository.get_candidate_profile_by_id(candidate_id)
        if candidate_profile is None:
            return _json_response(
                start_response,
                HTTPStatus.NOT_FOUND,
                _error_envelope(
                    request_id=request_id,
                    code="not_found",
                    message="Candidate profile not found",
                    retryable=False,
                ),
            )

        interview_history = self._repository.list_interview_sessions_for_candidate(candidate_id=candidate_id)
        feedback_history = self._repository.list_feedback_reports_for_candidate(candidate_id=candidate_id)
        progress_summary = self._progress_aggregator.aggregate(
            interview_sessions=interview_history,
            feedback_reports=feedback_history,
        )

        trajectory_plan_payload = self._build_trajectory_plan_payload(
            candidate_id=candidate_id,
            candidate_profile=candidate_profile,
            target_role=target_role,
            progress_summary=progress_summary,
            requested_horizon_months=resolved_horizon_months,
        )
        validation = self._schema_validator.validate("TrajectoryPlan", trajectory_plan_payload)
        if not validation.is_valid:
            issue_summary = [{"path": issue.path, "message": issue.message} for issue in validation.issues]
            return _json_response(
                start_response,
                HTTPStatus.UNPROCESSABLE_ENTITY,
                _error_envelope(
                    request_id=request_id,
                    code="invalid_trajectory_plan",
                    message="Generated TrajectoryPlan failed schema validation",
                    retryable=False,
                    details=issue_summary,
                ),
            )

        create_result = self._repository.create_or_get_trajectory_plan(
            idempotency_key=idempotency_key,
            request_payload=payload,
            trajectory_plan=trajectory_plan_payload,
        )
        if create_result.status == "candidate_not_found":
            return _json_response(
                start_response,
                HTTPStatus.NOT_FOUND,
                _error_envelope(
                    request_id=request_id,
                    code="not_found",
                    message="Candidate profile not found",
                    retryable=False,
                ),
            )
        if create_result.status == "idempotency_conflict":
            return _json_response(
                start_response,
                HTTPStatus.CONFLICT,
                _error_envelope(
                    request_id=request_id,
                    code="idempotency_key_conflict",
                    message="Idempotency-Key is already associated with a different request",
                    retryable=False,
                ),
            )
        if create_result.status == "version_conflict":
            details: list[dict[str, str]] = []
            if create_result.current_version is not None:
                details.append(
                    {
                        "field": "expected_version",
                        "reason": f"current version is {create_result.current_version}",
                    }
                )
            return _json_response(
                start_response,
                HTTPStatus.CONFLICT,
                _error_envelope(
                    request_id=request_id,
                    code="version_conflict",
                    message="expected_version does not match current trajectory plan version",
                    retryable=False,
                    details=details or None,
                ),
            )
        if create_result.plan is None:
            return _json_response(
                start_response,
                HTTPStatus.INTERNAL_SERVER_ERROR,
                _error_envelope(
                    request_id=request_id,
                    code="internal_error",
                    message="Trajectory plan could not be persisted",
                    retryable=True,
                ),
            )

        return _json_response(
            start_response,
            HTTPStatus.CREATED,
            _success_envelope(request_id=request_id, data=create_result.plan),
        )

    def _handle_get_trajectory_plan(
        self,
        start_response: Any,
        *,
        request_id: str,
        trajectory_plan_id: str,
    ) -> list[bytes]:
        payload = self._repository.get_trajectory_plan_by_id(trajectory_plan_id)
        if payload is None:
            return _json_response(
                start_response,
                HTTPStatus.NOT_FOUND,
                _error_envelope(
                    request_id=request_id,
                    code="not_found",
                    message="Trajectory plan not found",
                    retryable=False,
                ),
            )

        return _json_response(
            start_response,
            HTTPStatus.OK,
            _success_envelope(request_id=request_id, data=payload),
        )

    def _handle_append_interview_response(
        self,
        environ: dict[str, Any],
        start_response: Any,
        *,
        request_id: str,
        session_id: str,
    ) -> list[bytes]:
        idempotency_key = str(environ.get("HTTP_IDEMPOTENCY_KEY", "")).strip()
        if not idempotency_key:
            return _json_response(
                start_response,
                HTTPStatus.BAD_REQUEST,
                _error_envelope(
                    request_id=request_id,
                    code="invalid_request",
                    message="Idempotency-Key header is required",
                    retryable=False,
                    details=[{"field": "Idempotency-Key", "reason": "required"}],
                ),
            )

        payload, payload_error = _parse_json_payload(environ)
        if payload_error:
            return _json_response(
                start_response,
                HTTPStatus.BAD_REQUEST,
                _error_envelope(
                    request_id=request_id,
                    code="invalid_request",
                    message=payload_error,
                    retryable=False,
                ),
            )

        validation_errors = _validate_append_interview_response_payload(payload)
        if validation_errors:
            return _json_response(
                start_response,
                HTTPStatus.BAD_REQUEST,
                _error_envelope(
                    request_id=request_id,
                    code="invalid_request",
                    message="Request body validation failed",
                    retryable=False,
                    details=validation_errors,
                ),
            )

        current_session = self._repository.get_interview_session_by_id(session_id)
        if current_session is None:
            return _json_response(
                start_response,
                HTTPStatus.NOT_FOUND,
                _error_envelope(
                    request_id=request_id,
                    code="not_found",
                    message="Interview session not found",
                    retryable=False,
                ),
            )

        expected_version = payload.get("expected_version")
        if expected_version is not None and int(current_session.get("version", 0)) != int(expected_version):
            return _json_response(
                start_response,
                HTTPStatus.CONFLICT,
                _error_envelope(
                    request_id=request_id,
                    code="version_conflict",
                    message="Interview session version conflict",
                    retryable=False,
                    details=[
                        {
                            "field": "expected_version",
                            "reason": f"current version is {int(current_session.get('version', 0))}",
                        }
                    ],
                ),
            )

        try:
            updated_session, question_id, score = _apply_interview_response_to_session(
                current_session,
                payload,
                followup_selector=self._interview_followup_selector,
            )
        except ValueError as exc:
            return _json_response(
                start_response,
                HTTPStatus.BAD_REQUEST,
                _error_envelope(
                    request_id=request_id,
                    code="invalid_request",
                    message=str(exc),
                    retryable=False,
                ),
            )

        validation = self._schema_validator.validate("InterviewSession", updated_session)
        if not validation.is_valid:
            issue_summary = [{"path": issue.path, "message": issue.message} for issue in validation.issues]
            return _json_response(
                start_response,
                HTTPStatus.UNPROCESSABLE_ENTITY,
                _error_envelope(
                    request_id=request_id,
                    code="invalid_interview_session",
                    message="Updated InterviewSession failed schema validation",
                    retryable=False,
                    details=issue_summary,
                ),
            )

        apply_result = self._repository.apply_interview_response(
            session_id=session_id,
            idempotency_key=idempotency_key,
            request_payload=payload,
            updated_session=updated_session,
            question_id=question_id,
            response_text=str(payload["response"]),
            score=score,
        )

        if apply_result.status == "not_found":
            return _json_response(
                start_response,
                HTTPStatus.NOT_FOUND,
                _error_envelope(
                    request_id=request_id,
                    code="not_found",
                    message="Interview session not found",
                    retryable=False,
                ),
            )

        if apply_result.status == "idempotency_conflict":
            return _json_response(
                start_response,
                HTTPStatus.CONFLICT,
                _error_envelope(
                    request_id=request_id,
                    code="idempotency_key_conflict",
                    message="Idempotency-Key is already associated with a different request",
                    retryable=False,
                ),
            )

        if apply_result.status == "version_conflict":
            details = []
            if apply_result.current_version is not None:
                details.append(
                    {
                        "field": "session.version",
                        "reason": f"current version is {apply_result.current_version}",
                    }
                )
            return _json_response(
                start_response,
                HTTPStatus.CONFLICT,
                _error_envelope(
                    request_id=request_id,
                    code="version_conflict",
                    message="Interview session version conflict",
                    retryable=False,
                    details=details or None,
                ),
            )

        if apply_result.session is None:
            return _json_response(
                start_response,
                HTTPStatus.INTERNAL_SERVER_ERROR,
                _error_envelope(
                    request_id=request_id,
                    code="internal_error",
                    message="Interview session could not be loaded after update",
                    retryable=True,
                ),
            )

        return _json_response(
            start_response,
            HTTPStatus.OK,
            _success_envelope(request_id=request_id, data=apply_result.session),
        )

    def _handle_get_job_spec(self, start_response: Any, *, request_id: str, job_spec_id: str) -> list[bytes]:
        payload = self._repository.get_job_spec_by_id(job_spec_id)
        if payload is None:
            return _json_response(
                start_response,
                HTTPStatus.NOT_FOUND,
                _error_envelope(
                    request_id=request_id,
                    code="not_found",
                    message="Job spec not found",
                    retryable=False,
                ),
            )

        return _json_response(
            start_response,
            HTTPStatus.OK,
            _success_envelope(request_id=request_id, data=payload),
        )

    def _handle_patch_job_spec_review(
        self,
        environ: dict[str, Any],
        start_response: Any,
        *,
        request_id: str,
        job_spec_id: str,
    ) -> list[bytes]:
        payload, payload_error = _parse_json_payload(environ)
        if payload_error:
            return _json_response(
                start_response,
                HTTPStatus.BAD_REQUEST,
                _error_envelope(
                    request_id=request_id,
                    code="invalid_request",
                    message=payload_error,
                    retryable=False,
                ),
            )

        validation_errors = _validate_patch_review_payload(payload)
        if validation_errors:
            return _json_response(
                start_response,
                HTTPStatus.BAD_REQUEST,
                _error_envelope(
                    request_id=request_id,
                    code="invalid_request",
                    message="Request body validation failed",
                    retryable=False,
                    details=validation_errors,
                ),
            )

        patch_object = payload["patch"]
        patch_errors = _validate_job_spec_patch_object(patch_object)
        if patch_errors:
            return _json_response(
                start_response,
                HTTPStatus.BAD_REQUEST,
                _error_envelope(
                    request_id=request_id,
                    code="invalid_request",
                    message="Patch payload validation failed",
                    retryable=False,
                    details=patch_errors,
                ),
            )

        current_job_spec = self._repository.get_job_spec_by_id(job_spec_id)
        if current_job_spec is None:
            return _json_response(
                start_response,
                HTTPStatus.NOT_FOUND,
                _error_envelope(
                    request_id=request_id,
                    code="not_found",
                    message="Job spec not found",
                    retryable=False,
                ),
            )

        expected_version = int(payload["expected_version"])
        updated_job_spec = _apply_job_spec_patch(current_job_spec, patch_object)
        updated_job_spec["version"] = expected_version + 1

        validation = self._schema_validator.validate("JobSpec", updated_job_spec)
        if not validation.is_valid:
            issues = [{"path": issue.path, "message": issue.message} for issue in validation.issues]
            return _json_response(
                start_response,
                HTTPStatus.UNPROCESSABLE_ENTITY,
                _error_envelope(
                    request_id=request_id,
                    code="invalid_job_spec_patch",
                    message="Patched JobSpec failed schema validation",
                    retryable=False,
                    details=issues,
                ),
            )

        review_notes = payload.get("review_notes")
        reviewed_by = payload.get("reviewed_by")
        review_result = self._repository.apply_job_spec_review(
            job_spec_id=job_spec_id,
            expected_version=expected_version,
            updated_job_spec=updated_job_spec,
            patch=patch_object,
            review_notes=str(review_notes) if review_notes is not None else None,
            reviewed_by=str(reviewed_by) if reviewed_by is not None else None,
        )

        if review_result.status == "not_found":
            return _json_response(
                start_response,
                HTTPStatus.NOT_FOUND,
                _error_envelope(
                    request_id=request_id,
                    code="not_found",
                    message="Job spec not found",
                    retryable=False,
                ),
            )

        if review_result.status == "version_conflict":
            details = []
            if review_result.current_version is not None:
                details.append(
                    {
                        "field": "expected_version",
                        "reason": f"current version is {review_result.current_version}",
                    }
                )
            return _json_response(
                start_response,
                HTTPStatus.CONFLICT,
                _error_envelope(
                    request_id=request_id,
                    code="version_conflict",
                    message="Job spec version conflict",
                    retryable=False,
                    details=details or None,
                ),
            )

        if review_result.job_spec is None:
            return _json_response(
                start_response,
                HTTPStatus.INTERNAL_SERVER_ERROR,
                _error_envelope(
                    request_id=request_id,
                    code="internal_error",
                    message="Updated job spec could not be loaded",
                    retryable=True,
                ),
            )

        return _json_response(
            start_response,
            HTTPStatus.OK,
            _success_envelope(request_id=request_id, data=review_result.job_spec),
        )

    def _build_job_spec_payload(self, record: JobIngestionRecord) -> dict[str, Any]:
        extracted = self._extraction_worker.extract(source_type=record.source_type, source_value=record.source_value)
        sections = _sections_by_id(extracted.sections)

        responsibilities = _collect_lines(sections, preferred_keys=("responsibilities",))
        if not responsibilities:
            responsibilities = _collect_lines(sections, preferred_keys=("overview",))
        if not responsibilities:
            responsibilities = [extracted.role_title]
        responsibilities = [
            line for line in responsibilities if line.strip().lower() != extracted.role_title.strip().lower()
        ] or [extracted.role_title]

        required_lines = _collect_lines(sections, preferred_keys=("requirements",))
        preferred_lines = _collect_lines(sections, preferred_keys=("preferred_qualifications",))

        required_terms = _extract_skill_terms(required_lines, self._taxonomy_normalizer)
        preferred_terms = _extract_skill_terms(preferred_lines, self._taxonomy_normalizer)

        normalized_terms = _TAXONOMY_MODULE.normalize_job_requirement_terms(
            required_skills=required_terms,
            preferred_skills=preferred_terms,
            normalizer=self._taxonomy_normalizer,
        )

        required_skills = _normalized_term_labels(normalized_terms["required"])
        preferred_skills = _normalized_term_labels(normalized_terms["preferred"])
        competency_weights = _competency_weights(normalized_terms["required"], normalized_terms["preferred"])

        evidence_spans = _build_evidence_spans(
            responsibilities=responsibilities,
            required_terms=normalized_terms["required"],
            preferred_terms=normalized_terms["preferred"],
        )
        extraction_confidence = _extraction_confidence(evidence_spans)

        job_spec_suffix = record.ingestion_id[4:] if record.ingestion_id.startswith("ing_") else record.ingestion_id
        job_spec_id = f"job_{job_spec_suffix}"

        payload: dict[str, Any] = {
            "job_spec_id": job_spec_id,
            "source": {
                "type": record.source_type,
                "value": record.source_value,
                "captured_at": _utc_timestamp(),
            },
            "role_title": extracted.role_title,
            "responsibilities": responsibilities,
            "requirements": {
                "required_skills": required_skills,
                "preferred_skills": preferred_skills,
            },
            "competency_weights": competency_weights,
            "evidence_spans": evidence_spans,
            "extraction_confidence": extraction_confidence,
            "taxonomy_version": "m1-taxonomy-v1",
            "version": 1,
        }

        return payload

    def _build_candidate_profile_payload(self, record: CandidateIngestionRecord) -> dict[str, Any]:
        return self._candidate_profile_parser.parse(
            ingestion_id=record.ingestion_id,
            candidate_id=record.candidate_id,
            cv_text=record.cv_text,
            cv_document_ref=record.cv_document_ref,
            target_roles=record.target_roles,
            story_notes=record.story_notes,
        )

    def _build_candidate_storybank_payload(
        self,
        *,
        candidate_profile_payload: dict[str, Any],
        record: CandidateIngestionRecord,
    ) -> list[dict[str, Any]]:
        return self._candidate_storybank_generator.generate(
            candidate_id=str(candidate_profile_payload["candidate_id"]),
            experiences=list(candidate_profile_payload.get("experience", [])),
            story_notes=record.story_notes,
        )

    def _build_interview_session_payload(
        self,
        *,
        job_spec_id: str,
        candidate_id: str,
        mode: str,
        job_spec: dict[str, Any],
        candidate_profile: dict[str, Any],
    ) -> dict[str, Any]:
        session_id = f"sess_{uuid4().hex}"
        questions = self._interview_question_planner.plan_opening_questions(
            session_id=session_id,
            job_spec=job_spec,
            candidate_profile=candidate_profile,
        )

        return {
            "session_id": session_id,
            "job_spec_id": job_spec_id,
            "candidate_id": candidate_id,
            "mode": mode,
            "status": "in_progress",
            "questions": questions,
            "scores": {},
            "overall_score": 0.0,
            "root_cause_tags": [],
            "created_at": _utc_timestamp(),
            "version": 1,
        }

    def _build_feedback_report_payload(self, session: dict[str, Any]) -> dict[str, Any]:
        session_id = str(session["session_id"])
        competency_scores, aggregated_overall_score = _aggregate_feedback_scores(session)
        top_gaps = _feedback_top_gaps(session=session, competency_scores=competency_scores)
        action_plan = _feedback_action_plan(top_gaps)
        answer_rewrites = _feedback_answer_rewrites(session=session, top_gaps=top_gaps)

        payload: dict[str, Any] = {
            "feedback_report_id": f"fb_{uuid4().hex}",
            "session_id": session_id,
            "top_gaps": top_gaps,
            "action_plan": action_plan,
            "overall_score": round(aggregated_overall_score, 2),
            "generated_at": _utc_timestamp(),
        }
        if competency_scores:
            payload["competency_scores"] = competency_scores
        if answer_rewrites:
            payload["answer_rewrites"] = answer_rewrites

        if aggregated_overall_score < 70.0:
            payload["trajectory_update"] = "Focus next sessions on critical gap competencies before raising difficulty."

        return payload

    def _build_negotiation_plan_payload(
        self,
        *,
        candidate_id: str,
        candidate_profile: dict[str, Any],
        target_role: str,
        request_payload: dict[str, Any],
        interview_history: list[dict[str, Any]],
        feedback_history: list[dict[str, Any]],
        latest_trajectory_plan: dict[str, Any] | None,
    ) -> dict[str, Any]:
        current_base_salary_raw = request_payload.get("current_base_salary")
        current_base_salary = (
            int(current_base_salary_raw)
            if isinstance(current_base_salary_raw, int)
            and not isinstance(current_base_salary_raw, bool)
            and current_base_salary_raw >= 0
            else None
        )
        target_base_salary_raw = request_payload.get("target_base_salary")
        target_base_salary = (
            int(target_base_salary_raw)
            if isinstance(target_base_salary_raw, int)
            and not isinstance(target_base_salary_raw, bool)
            and target_base_salary_raw >= 0
            else None
        )
        compensation_currency_raw = request_payload.get("compensation_currency")
        compensation_currency = (
            str(compensation_currency_raw).strip().upper()
            if isinstance(compensation_currency_raw, str) and compensation_currency_raw.strip()
            else "USD"
        )

        if target_base_salary is None and current_base_salary is None:
            target_base_salary = 180000
            current_base_salary = 160000
        elif target_base_salary is None and current_base_salary is not None:
            target_base_salary = current_base_salary + 15000
        elif target_base_salary is not None and current_base_salary is None:
            current_base_salary = max(0, target_base_salary - 20000)

        assert current_base_salary is not None
        assert target_base_salary is not None

        negotiation_context = self._negotiation_context_aggregator.aggregate(
            candidate_id=candidate_id,
            target_role=target_role,
            request_payload=request_payload,
            candidate_profile=candidate_profile,
            interview_sessions=interview_history,
            feedback_reports=feedback_history,
            latest_trajectory_plan=latest_trajectory_plan,
        )
        compensation_adjustments = (
            negotiation_context.get("compensation_adjustments")
            if isinstance(negotiation_context.get("compensation_adjustments"), dict)
            else {}
        )
        market_uplift_pct = _coerce_negotiation_fraction(
            compensation_adjustments.get("market_uplift_pct"),
            minimum=-0.10,
            maximum=0.30,
            default=0.04,
        )
        total_uplift_pct = _coerce_negotiation_fraction(
            compensation_adjustments.get("total_uplift_pct"),
            minimum=-0.10,
            maximum=0.30,
            default=0.02,
        )
        walk_away_floor_pct = _coerce_negotiation_fraction(
            compensation_adjustments.get("walk_away_floor_pct"),
            minimum=0.80,
            maximum=0.99,
            default=0.90,
        )
        confidence = _coerce_negotiation_fraction(
            compensation_adjustments.get("confidence"),
            minimum=0.50,
            maximum=0.99,
            default=0.60,
        )

        base_anchor = max(target_base_salary, current_base_salary + 10000)
        adjusted_anchor = int(round(base_anchor * (1.0 + total_uplift_pct)))
        anchor_base_salary = _round_compensation_to_500(max(base_anchor, adjusted_anchor))

        walk_away_base_salary = _round_compensation_to_500(
            max(current_base_salary, int(round(target_base_salary * walk_away_floor_pct)))
        )
        if walk_away_base_salary > anchor_base_salary:
            walk_away_base_salary = anchor_base_salary

        market_reference_base_salary = _round_compensation_to_500(
            max(target_base_salary, int(round(target_base_salary * (1.0 + max(0.0, market_uplift_pct)))))
        )
        recommended_counter_base_salary = _round_compensation_to_500(
            max(target_base_salary, int(round((target_base_salary + anchor_base_salary) / 2.0)))
        )
        if recommended_counter_base_salary < walk_away_base_salary:
            recommended_counter_base_salary = walk_away_base_salary
        if recommended_counter_base_salary > anchor_base_salary:
            recommended_counter_base_salary = anchor_base_salary

        compensation_targets = {
            "currency": compensation_currency,
            "current_base_salary": current_base_salary,
            "target_base_salary": target_base_salary,
            "anchor_base_salary": anchor_base_salary,
            "walk_away_base_salary": walk_away_base_salary,
            "recommended_counter_base_salary": recommended_counter_base_salary,
            "market_reference_base_salary": market_reference_base_salary,
            "confidence": confidence,
        }

        leverage_signals = _normalize_negotiation_leverage_signals(negotiation_context.get("leverage_signals"))
        risk_signals = _normalize_negotiation_risk_signals(negotiation_context.get("risk_signals"))
        evidence_links = _normalize_negotiation_evidence_links(negotiation_context.get("evidence_links"))

        generated_strategy = self._negotiation_strategy_generator.generate(
            target_role=target_role,
            compensation_targets=compensation_targets,
            leverage_signals=leverage_signals,
            risk_signals=risk_signals,
            evidence_links=evidence_links,
        )

        anchor_band = _normalize_negotiation_anchor_band(
            generated_strategy.get("anchor_band"),
            compensation_targets=compensation_targets,
        )
        concession_ladder = _normalize_negotiation_concession_ladder(
            generated_strategy.get("concession_ladder"),
            anchor_band=anchor_band,
            leverage_signals=leverage_signals,
            risk_signals=risk_signals,
        )
        objection_playbook = _normalize_negotiation_objection_playbook(
            generated_strategy.get("objection_playbook"),
            risk_signals=risk_signals,
            leverage_signals=leverage_signals,
            evidence_links=evidence_links,
            anchor_band=anchor_band,
        )
        talking_points = _normalize_negotiation_talking_points(
            generated_strategy.get("talking_points"),
            anchor_band=anchor_band,
            leverage_signals=leverage_signals,
            risk_signals=risk_signals,
        )
        strategy_summary_raw = generated_strategy.get("strategy_summary")
        strategy_summary = str(strategy_summary_raw).strip() if isinstance(strategy_summary_raw, str) else ""
        if not strategy_summary:
            lead_leverage = (
                str(leverage_signals[0].get("signal", "")).replace("_", " ")
                if leverage_signals
                else "performance momentum"
            )
            lead_risk = (
                str(risk_signals[0].get("signal", "")).replace("_", " ")
                if risk_signals
                else "timeline pressure"
            )
            strategy_summary = (
                f"Anchor near {anchor_band.get('ceiling_base_salary', anchor_base_salary)} with {lead_leverage}, "
                f"hold floor at {anchor_band.get('floor_base_salary', walk_away_base_salary)}, and pre-handle {lead_risk}."
            )

        payload: dict[str, Any] = {
            "negotiation_plan_id": f"np_{uuid4().hex}",
            "candidate_id": candidate_id,
            "target_role": target_role,
            "strategy_summary": strategy_summary,
            "compensation_targets": compensation_targets,
            "leverage_signals": leverage_signals,
            "risk_signals": risk_signals,
            "evidence_links": evidence_links,
            "anchor_band": anchor_band,
            "concession_ladder": concession_ladder,
            "objection_playbook": objection_playbook,
            "talking_points": talking_points,
            "follow_up_actions": [
                {
                    "day_offset": 0,
                    "action": "Send same-day thank-you note reinforcing top value proposition and enthusiasm.",
                },
                {
                    "day_offset": 2,
                    "action": "Share concise accomplishment bullets tied to role outcomes and compensation rationale.",
                },
                {
                    "day_offset": 5,
                    "action": "Request next-step timeline clarity and confirm decision window for offer response.",
                },
            ],
            "generated_at": _utc_timestamp(),
        }

        offer_deadline_date = request_payload.get("offer_deadline_date")
        if isinstance(offer_deadline_date, str) and offer_deadline_date.strip():
            payload["offer_deadline_date"] = offer_deadline_date.strip()

        return payload

    def _build_trajectory_plan_payload(
        self,
        *,
        candidate_id: str,
        candidate_profile: dict[str, Any],
        target_role: str,
        progress_summary: dict[str, Any],
        requested_horizon_months: int | None = None,
    ) -> dict[str, Any]:
        generated_plan = self._trajectory_planner.generate(
            candidate_profile=candidate_profile,
            target_role=target_role,
            progress_summary=progress_summary,
        )

        current_metrics = progress_summary.get("current") if isinstance(progress_summary, dict) else None
        current_overall: float | None = None
        if isinstance(current_metrics, dict):
            maybe_score = current_metrics.get("overall_score")
            if isinstance(maybe_score, (int, float)) and not isinstance(maybe_score, bool):
                current_overall = round(float(maybe_score), 2)

        horizon_months = 3
        role_readiness_score = current_overall if current_overall is not None else 65.0
        milestones: list[dict[str, Any]] = []
        weekly_plan: list[dict[str, Any]] = []

        if isinstance(generated_plan, dict):
            raw_horizon = generated_plan.get("horizon_months")
            if isinstance(raw_horizon, int):
                horizon_months = max(1, min(24, raw_horizon))

            raw_readiness = generated_plan.get("role_readiness_score")
            if isinstance(raw_readiness, (int, float)) and not isinstance(raw_readiness, bool):
                role_readiness_score = max(0.0, min(100.0, round(float(raw_readiness), 2)))

            raw_milestones = generated_plan.get("milestones")
            if isinstance(raw_milestones, list):
                milestones = [item for item in raw_milestones if isinstance(item, dict)]

            raw_weekly = generated_plan.get("weekly_plan")
            if isinstance(raw_weekly, list):
                weekly_plan = [item for item in raw_weekly if isinstance(item, dict)]

        if isinstance(requested_horizon_months, int):
            horizon_months = max(1, min(24, requested_horizon_months))

        return {
            "trajectory_plan_id": f"tp_{uuid4().hex}",
            "candidate_id": candidate_id,
            "target_role": target_role,
            "horizon_months": horizon_months,
            "role_readiness_score": role_readiness_score,
            "milestones": milestones,
            "weekly_plan": weekly_plan,
            "progress_summary": progress_summary,
            "generated_at": _utc_timestamp(),
        }

    def _build_candidate_progress_dashboard_payload(
        self,
        *,
        candidate_id: str,
        progress_summary: dict[str, Any],
        latest_trajectory_plan: dict[str, Any] | None,
    ) -> dict[str, Any]:
        summary = progress_summary if isinstance(progress_summary, dict) else {}
        competency_trends = _normalize_progress_competency_trends(summary.get("competency_trends"))
        latest_trajectory_metadata = _latest_trajectory_plan_dashboard_metadata(latest_trajectory_plan)

        return {
            "candidate_id": candidate_id,
            "progress_summary": summary,
            "competency_trend_cards": {
                "top_improving": _build_top_improving_competency_cards(competency_trends),
                "top_risk": _build_top_risk_competency_cards(competency_trends),
            },
            "readiness_signals": _build_dashboard_readiness_signals(
                progress_summary=summary,
                latest_trajectory_metadata=latest_trajectory_metadata,
            ),
            "latest_trajectory_plan": latest_trajectory_metadata,
        }

    def _build_competency_fit_payload(
        self,
        *,
        job_spec_id: str,
        candidate_id: str,
        job_spec: dict[str, Any],
        candidate_profile: dict[str, Any],
    ) -> dict[str, Any]:
        required_weights = _resolve_job_required_competency_weights(
            job_spec=job_spec,
            taxonomy_normalizer=self._taxonomy_normalizer,
        )
        candidate_scores = _resolve_candidate_competency_scores(
            candidate_profile=candidate_profile,
            taxonomy_normalizer=self._taxonomy_normalizer,
        )

        competencies: list[dict[str, Any]] = []
        total_required = 0.0
        total_covered = 0.0

        for competency_id, required_weight in sorted(required_weights.items()):
            candidate_score = max(0.0, min(1.0, float(candidate_scores.get(competency_id, 0.0))))
            gap = max(0.0, required_weight - candidate_score)
            fit_ratio = 1.0 if required_weight <= 0.0 else min(1.0, candidate_score / required_weight)
            total_required += required_weight
            total_covered += min(required_weight, candidate_score)
            competencies.append(
                {
                    "competency": competency_id,
                    "required_weight": round(required_weight, 3),
                    "candidate_score": round(candidate_score, 3),
                    "gap": round(gap, 3),
                    "fit_ratio": round(fit_ratio, 3),
                }
            )

        overall_fit_score = 0.0 if total_required <= 0.0 else round((total_covered / total_required) * 100.0, 2)
        covered_count = len([item for item in competencies if item["candidate_score"] > 0.0])
        coverage_ratio = 0.0 if not competencies else round(covered_count / len(competencies), 3)
        top_gaps = sorted(competencies, key=lambda item: (-float(item["gap"]), str(item["competency"])))[:5]

        return {
            "job_spec_id": job_spec_id,
            "candidate_id": candidate_id,
            "overall_fit_score": overall_fit_score,
            "coverage_ratio": coverage_ratio,
            "competencies": competencies,
            "top_gaps": top_gaps,
        }


def create_app(db_path: str | Path | None = None) -> JobIngestionAPI:
    resolved_db_path = db_path or os.environ.get("JOBCOACH_DB_PATH") or ".tmp/migrate-local.sqlite3"
    extraction_worker = _JOB_EXTRACTION_MODULE.JobExtractionWorker()
    taxonomy_normalizer = _TAXONOMY_MODULE.TaxonomyNormalizer.from_file()
    schema_validator = _SCHEMA_VALIDATOR_MODULE.CoreSchemaValidator.from_file()
    candidate_profile_parser = _CANDIDATE_PROFILE_MODULE.CandidateProfileParser()
    candidate_storybank_generator = _CANDIDATE_STORYBANK_MODULE.CandidateStorybankGenerator()
    interview_question_planner = _INTERVIEW_PLANNER_MODULE.DeterministicQuestionPlanner()
    interview_followup_selector = _INTERVIEW_FOLLOWUP_MODULE.AdaptiveFollowupSelector()
    progress_aggregator = _PROGRESS_AGGREGATOR_MODULE.LongitudinalProgressAggregator()
    trajectory_planner = _TRAJECTORY_PLANNER_MODULE.DeterministicTrajectoryPlanner()
    negotiation_context_aggregator = _NEGOTIATION_CONTEXT_AGGREGATOR_MODULE.DeterministicNegotiationContextAggregator()
    negotiation_strategy_generator = _NEGOTIATION_STRATEGY_GENERATOR_MODULE.DeterministicNegotiationStrategyGenerator()
    return JobIngestionAPI(
        repository=SQLiteJobIngestionRepository(resolved_db_path),
        extraction_worker=extraction_worker,
        taxonomy_normalizer=taxonomy_normalizer,
        schema_validator=schema_validator,
        candidate_profile_parser=candidate_profile_parser,
        candidate_storybank_generator=candidate_storybank_generator,
        interview_question_planner=interview_question_planner,
        interview_followup_selector=interview_followup_selector,
        progress_aggregator=progress_aggregator,
        trajectory_planner=trajectory_planner,
        negotiation_context_aggregator=negotiation_context_aggregator,
        negotiation_strategy_generator=negotiation_strategy_generator,
    )


def _parse_json_payload(environ: dict[str, Any]) -> tuple[dict[str, Any], str | None]:
    input_stream = environ.get("wsgi.input")
    if input_stream is None:
        return {}, "Request body must be a JSON object"

    raw_content_length = environ.get("CONTENT_LENGTH")
    if raw_content_length in (None, ""):
        body_bytes = input_stream.read()
    else:
        try:
            content_length = int(raw_content_length)
        except ValueError:
            return {}, "Invalid Content-Length header"
        body_bytes = input_stream.read(content_length) if content_length > 0 else b""
    if not body_bytes:
        return {}, "Request body must be a JSON object"

    try:
        payload = json.loads(body_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {}, "Request body must be valid JSON"

    if not isinstance(payload, dict):
        return {}, "Request body must be a JSON object"

    return payload, None


def _validate_create_payload(payload: dict[str, Any]) -> list[dict[str, str]]:
    errors: list[dict[str, str]] = []

    source_type = payload.get("source_type")
    if not isinstance(source_type, str) or source_type not in SOURCE_TYPE_VALUES:
        errors.append({"field": "source_type", "reason": "must be one of: url, text, document_ref"})

    source_value = payload.get("source_value")
    if not isinstance(source_value, str) or not source_value:
        errors.append({"field": "source_value", "reason": "must be a non-empty string"})

    target_locale = payload.get("target_locale")
    if target_locale is not None and (not isinstance(target_locale, str) or not target_locale):
        errors.append({"field": "target_locale", "reason": "must be a non-empty string when provided"})

    return errors


def _validate_create_candidate_payload(payload: dict[str, Any]) -> list[dict[str, str]]:
    errors: list[dict[str, str]] = []

    candidate_id = payload.get("candidate_id")
    if candidate_id is not None and (not isinstance(candidate_id, str) or not candidate_id):
        errors.append({"field": "candidate_id", "reason": "must be a non-empty string when provided"})

    cv_text = payload.get("cv_text")
    has_cv_text = isinstance(cv_text, str) and bool(cv_text.strip())
    if cv_text is not None and not has_cv_text:
        errors.append({"field": "cv_text", "reason": "must be a non-empty string when provided"})

    cv_document_ref = payload.get("cv_document_ref")
    has_cv_document_ref = isinstance(cv_document_ref, str) and bool(cv_document_ref.strip())
    if cv_document_ref is not None and not has_cv_document_ref:
        errors.append({"field": "cv_document_ref", "reason": "must be a non-empty string when provided"})

    if has_cv_text == has_cv_document_ref:
        errors.append(
            {
                "field": "cv_text/cv_document_ref",
                "reason": "exactly one of cv_text or cv_document_ref must be provided",
            }
        )

    story_notes = payload.get("story_notes")
    if story_notes is not None:
        if not isinstance(story_notes, list):
            errors.append({"field": "story_notes", "reason": "must be an array of strings when provided"})
        else:
            for idx, value in enumerate(story_notes):
                if not isinstance(value, str):
                    errors.append({"field": f"story_notes[{idx}]", "reason": "must be a string"})

    target_roles = payload.get("target_roles")
    if target_roles is not None:
        if not isinstance(target_roles, list):
            errors.append({"field": "target_roles", "reason": "must be an array of strings when provided"})
        else:
            for idx, value in enumerate(target_roles):
                if not isinstance(value, str):
                    errors.append({"field": f"target_roles[{idx}]", "reason": "must be a string"})

    target_locale = payload.get("target_locale")
    if target_locale is not None and (not isinstance(target_locale, str) or not target_locale):
        errors.append({"field": "target_locale", "reason": "must be a non-empty string when provided"})

    return errors


def _validate_create_competency_fit_payload(payload: dict[str, Any]) -> list[dict[str, str]]:
    errors: list[dict[str, str]] = []

    job_spec_id = payload.get("job_spec_id")
    if not isinstance(job_spec_id, str) or not job_spec_id.strip():
        errors.append({"field": "job_spec_id", "reason": "must be a non-empty string"})

    candidate_id = payload.get("candidate_id")
    if not isinstance(candidate_id, str) or not candidate_id.strip():
        errors.append({"field": "candidate_id", "reason": "must be a non-empty string"})

    return errors


def _validate_create_interview_session_payload(payload: dict[str, Any]) -> list[dict[str, str]]:
    errors: list[dict[str, str]] = []

    job_spec_id = payload.get("job_spec_id")
    if not isinstance(job_spec_id, str) or not job_spec_id.strip():
        errors.append({"field": "job_spec_id", "reason": "must be a non-empty string"})

    candidate_id = payload.get("candidate_id")
    if not isinstance(candidate_id, str) or not candidate_id.strip():
        errors.append({"field": "candidate_id", "reason": "must be a non-empty string"})

    mode = payload.get("mode")
    if mode is not None and (not isinstance(mode, str) or mode not in INTERVIEW_MODE_VALUES):
        errors.append({"field": "mode", "reason": "must be one of: mock_interview, drill, negotiation"})

    return errors


def _validate_create_feedback_report_payload(payload: dict[str, Any]) -> list[dict[str, str]]:
    errors: list[dict[str, str]] = []

    session_id = payload.get("session_id")
    if not isinstance(session_id, str) or not session_id.strip():
        errors.append({"field": "session_id", "reason": "must be a non-empty string"})

    expected_version = payload.get("expected_version")
    if expected_version is not None and (
        not isinstance(expected_version, int) or isinstance(expected_version, bool) or expected_version < 0
    ):
        errors.append({"field": "expected_version", "reason": "must be an integer >= 0 when provided"})

    regenerate = payload.get("regenerate")
    if regenerate is not None and not isinstance(regenerate, bool):
        errors.append({"field": "regenerate", "reason": "must be a boolean when provided"})

    return errors


def _validate_create_negotiation_plan_payload(payload: dict[str, Any]) -> list[dict[str, str]]:
    errors: list[dict[str, str]] = []

    candidate_id = payload.get("candidate_id")
    if not isinstance(candidate_id, str) or not candidate_id.strip():
        errors.append({"field": "candidate_id", "reason": "must be a non-empty string"})

    target_role = payload.get("target_role")
    if not isinstance(target_role, str) or not target_role.strip():
        errors.append({"field": "target_role", "reason": "must be a non-empty string"})

    compensation_currency = payload.get("compensation_currency")
    if compensation_currency is not None and (not isinstance(compensation_currency, str) or not compensation_currency.strip()):
        errors.append({"field": "compensation_currency", "reason": "must be a non-empty string when provided"})

    current_base_salary = payload.get("current_base_salary")
    if current_base_salary is not None and (
        not isinstance(current_base_salary, int) or isinstance(current_base_salary, bool) or current_base_salary < 0
    ):
        errors.append({"field": "current_base_salary", "reason": "must be an integer >= 0 when provided"})

    target_base_salary = payload.get("target_base_salary")
    if target_base_salary is not None and (
        not isinstance(target_base_salary, int) or isinstance(target_base_salary, bool) or target_base_salary < 0
    ):
        errors.append({"field": "target_base_salary", "reason": "must be an integer >= 0 when provided"})

    if (
        isinstance(current_base_salary, int)
        and not isinstance(current_base_salary, bool)
        and isinstance(target_base_salary, int)
        and not isinstance(target_base_salary, bool)
        and target_base_salary < current_base_salary
    ):
        errors.append({"field": "target_base_salary", "reason": "must be >= current_base_salary when both are provided"})

    offer_deadline_date = payload.get("offer_deadline_date")
    if offer_deadline_date is not None and (not isinstance(offer_deadline_date, str) or not offer_deadline_date.strip()):
        errors.append({"field": "offer_deadline_date", "reason": "must be a non-empty ISO-8601 date string when provided"})

    return errors


def _validate_create_trajectory_plan_payload(payload: dict[str, Any]) -> list[dict[str, str]]:
    errors: list[dict[str, str]] = []

    candidate_id = payload.get("candidate_id")
    if not isinstance(candidate_id, str) or not candidate_id.strip():
        errors.append({"field": "candidate_id", "reason": "must be a non-empty string"})

    target_role = payload.get("target_role")
    if not isinstance(target_role, str) or not target_role.strip():
        errors.append({"field": "target_role", "reason": "must be a non-empty string"})

    horizon_months = payload.get("horizon_months")
    if horizon_months is not None and (
        not isinstance(horizon_months, int)
        or isinstance(horizon_months, bool)
        or horizon_months < 1
        or horizon_months > 24
    ):
        errors.append({"field": "horizon_months", "reason": "must be an integer between 1 and 24 when provided"})

    expected_version = payload.get("expected_version")
    if expected_version is not None and (
        not isinstance(expected_version, int) or isinstance(expected_version, bool) or expected_version < 0
    ):
        errors.append({"field": "expected_version", "reason": "must be an integer >= 0 when provided"})

    regenerate = payload.get("regenerate")
    if regenerate is not None and not isinstance(regenerate, bool):
        errors.append({"field": "regenerate", "reason": "must be a boolean when provided"})

    return errors


def _round_compensation_to_500(raw_value: int) -> int:
    return int(round(float(raw_value) / 500.0) * 500)


def _coerce_negotiation_fraction(
    raw_value: Any,
    *,
    minimum: float,
    maximum: float,
    default: float,
) -> float:
    if not isinstance(raw_value, (int, float)) or isinstance(raw_value, bool):
        return default
    return round(max(minimum, min(maximum, float(raw_value))), 4)


def _normalize_negotiation_leverage_signals(raw_signals: Any) -> list[dict[str, Any]]:
    if not isinstance(raw_signals, list):
        return [
            {
                "signal": "skill_depth",
                "strength": "medium",
                "score": 62.0,
                "evidence": "Candidate skill profile provides baseline leverage support.",
            }
        ]

    normalized: list[dict[str, Any]] = []
    for raw in raw_signals:
        if not isinstance(raw, dict):
            continue
        signal = str(raw.get("signal", "")).strip()
        strength = str(raw.get("strength", "")).strip().lower()
        score = raw.get("score")
        evidence = str(raw.get("evidence", "")).strip()
        if not signal or strength not in {"low", "medium", "high"} or not evidence:
            continue
        if not isinstance(score, (int, float)) or isinstance(score, bool):
            continue
        bounded_score = max(0.0, min(100.0, round(float(score), 2)))
        normalized.append(
            {
                "signal": signal,
                "strength": strength,
                "score": bounded_score,
                "evidence": evidence,
            }
        )

    normalized.sort(key=lambda item: (-float(item["score"]), str(item["signal"])))
    return normalized[:5] if normalized else _normalize_negotiation_leverage_signals(None)


def _normalize_negotiation_risk_signals(raw_signals: Any) -> list[dict[str, Any]]:
    if not isinstance(raw_signals, list):
        return [
            {
                "signal": "timeline_risk",
                "severity": "medium",
                "score": 45.0,
                "evidence": "Offer timeline uncertainty requires active risk management.",
            }
        ]

    severity_rank = {"critical": 3, "high": 2, "medium": 1, "low": 0}
    normalized: list[dict[str, Any]] = []
    for raw in raw_signals:
        if not isinstance(raw, dict):
            continue
        signal = str(raw.get("signal", "")).strip()
        severity = str(raw.get("severity", "")).strip().lower()
        score = raw.get("score")
        evidence = str(raw.get("evidence", "")).strip()
        if not signal or severity not in severity_rank or not evidence:
            continue
        if not isinstance(score, (int, float)) or isinstance(score, bool):
            continue
        bounded_score = max(0.0, min(100.0, round(float(score), 2)))
        normalized.append(
            {
                "signal": signal,
                "severity": severity,
                "score": bounded_score,
                "evidence": evidence,
            }
        )

    normalized.sort(
        key=lambda item: (
            -severity_rank[str(item["severity"])],
            -float(item["score"]),
            str(item["signal"]),
        )
    )
    return normalized[:5] if normalized else _normalize_negotiation_risk_signals(None)


def _normalize_negotiation_evidence_links(raw_links: Any) -> list[dict[str, str]]:
    if not isinstance(raw_links, list):
        return [
            {
                "source_type": "offer_input",
                "source_id": "candidate",
                "detail": "Fallback offer context used for negotiation evidence.",
            }
        ]

    order = {
        "offer_input": 0,
        "candidate_profile": 1,
        "interview_session": 2,
        "feedback_report": 3,
        "trajectory_plan": 4,
    }
    dedup: dict[tuple[str, str, str], dict[str, str]] = {}
    for raw in raw_links:
        if not isinstance(raw, dict):
            continue
        source_type = str(raw.get("source_type", "")).strip()
        source_id = str(raw.get("source_id", "")).strip()
        detail = str(raw.get("detail", "")).strip()
        if not source_type or not source_id or not detail:
            continue
        dedup[(source_type, source_id, detail)] = {
            "source_type": source_type,
            "source_id": source_id,
            "detail": detail,
        }

    normalized = sorted(
        dedup.values(),
        key=lambda item: (
            order.get(str(item["source_type"]), 99),
            str(item["source_id"]),
            str(item["detail"]),
        ),
    )
    return normalized[:5] if normalized else _normalize_negotiation_evidence_links(None)


def _normalize_negotiation_anchor_band(
    raw_band: Any,
    *,
    compensation_targets: dict[str, Any],
) -> dict[str, Any]:
    currency = str(compensation_targets.get("currency", "USD")).strip().upper() or "USD"
    fallback_floor = compensation_targets.get("walk_away_base_salary")
    fallback_target = compensation_targets.get("recommended_counter_base_salary")
    fallback_ceiling = compensation_targets.get("anchor_base_salary")
    floor = (
        int(fallback_floor)
        if isinstance(fallback_floor, int) and not isinstance(fallback_floor, bool) and fallback_floor >= 0
        else 0
    )
    target = (
        int(fallback_target)
        if isinstance(fallback_target, int) and not isinstance(fallback_target, bool) and fallback_target >= 0
        else floor
    )
    ceiling = (
        int(fallback_ceiling)
        if isinstance(fallback_ceiling, int) and not isinstance(fallback_ceiling, bool) and fallback_ceiling >= 0
        else max(floor, target)
    )
    rationale = (
        f"Anchor at {ceiling}, target {target}, and hold {floor} as minimum acceptable base salary."
    )

    if isinstance(raw_band, dict):
        raw_currency = raw_band.get("currency")
        if isinstance(raw_currency, str) and raw_currency.strip():
            currency = raw_currency.strip().upper()

        raw_floor = raw_band.get("floor_base_salary")
        if isinstance(raw_floor, int) and not isinstance(raw_floor, bool) and raw_floor >= 0:
            floor = raw_floor

        raw_target = raw_band.get("target_base_salary")
        if isinstance(raw_target, int) and not isinstance(raw_target, bool) and raw_target >= 0:
            target = raw_target

        raw_ceiling = raw_band.get("ceiling_base_salary")
        if isinstance(raw_ceiling, int) and not isinstance(raw_ceiling, bool) and raw_ceiling >= 0:
            ceiling = raw_ceiling

        raw_rationale = raw_band.get("rationale")
        if isinstance(raw_rationale, str) and raw_rationale.strip():
            rationale = raw_rationale.strip()

    floor = _round_compensation_to_500(max(0, floor))
    ceiling = _round_compensation_to_500(max(floor, ceiling))
    target = _round_compensation_to_500(max(floor, min(target, ceiling)))

    return {
        "currency": currency,
        "floor_base_salary": floor,
        "target_base_salary": target,
        "ceiling_base_salary": ceiling,
        "rationale": rationale,
    }


def _normalize_negotiation_concession_ladder(
    raw_ladder: Any,
    *,
    anchor_band: dict[str, Any],
    leverage_signals: list[dict[str, Any]],
    risk_signals: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    floor = int(anchor_band.get("floor_base_salary", 0))
    target = int(anchor_band.get("target_base_salary", floor))
    ceiling = int(anchor_band.get("ceiling_base_salary", max(floor, target)))

    normalized: list[dict[str, Any]] = []
    if isinstance(raw_ladder, list):
        for raw in raw_ladder:
            if not isinstance(raw, dict):
                continue
            step = raw.get("step")
            ask = raw.get("ask_base_salary")
            trigger = str(raw.get("trigger", "")).strip()
            concession = str(raw.get("concession", "")).strip()
            exchange_for = str(raw.get("exchange_for", "")).strip()
            evidence = str(raw.get("evidence", "")).strip()
            if (
                not isinstance(step, int)
                or isinstance(step, bool)
                or step < 1
                or not isinstance(ask, int)
                or isinstance(ask, bool)
                or ask < 0
                or not trigger
                or not concession
                or not exchange_for
                or not evidence
            ):
                continue
            normalized.append(
                {
                    "step": step,
                    "ask_base_salary": _round_compensation_to_500(max(floor, min(ask, ceiling))),
                    "trigger": trigger,
                    "concession": concession,
                    "exchange_for": exchange_for,
                    "evidence": evidence,
                }
            )

    if not normalized:
        midpoint = _round_compensation_to_500(max(target, ceiling - int(round(max(0, ceiling - floor) * 0.45))))
        asks = [ceiling, midpoint, target]
        deduped_asks: list[int] = []
        seen_asks: set[int] = set()
        for ask in asks:
            normalized_ask = _round_compensation_to_500(max(floor, min(ask, ceiling)))
            if normalized_ask in seen_asks:
                continue
            seen_asks.add(normalized_ask)
            deduped_asks.append(normalized_ask)
        if len(deduped_asks) < 2:
            deduped_asks.append(floor)

        for index, ask in enumerate(deduped_asks):
            leverage = leverage_signals[min(index, len(leverage_signals) - 1)] if leverage_signals else {}
            risk = risk_signals[min(index, len(risk_signals) - 1)] if risk_signals else {}
            normalized.append(
                {
                    "step": index + 1,
                    "ask_base_salary": ask,
                    "trigger": f"If employer raises {str(risk.get('signal', 'timeline_risk')).replace('_', ' ')} concerns.",
                    "concession": "Reduce base ask in controlled increments while preserving role scope.",
                    "exchange_for": "Written commitments on review timing, level scope, or non-base upside.",
                    "evidence": str(
                        leverage.get("evidence", "Use readiness and performance context to justify concessions.")
                    ),
                }
            )

    normalized.sort(key=lambda item: (int(item["step"]), -int(item["ask_base_salary"])))
    reindexed: list[dict[str, Any]] = []
    previous_ask: int | None = None
    for index, entry in enumerate(normalized[:4]):
        ask_value = int(entry["ask_base_salary"])
        if previous_ask is not None:
            ask_value = min(previous_ask, ask_value)
            ask_value = max(floor, ask_value)
        previous_ask = ask_value
        reindexed.append(
            {
                "step": index + 1,
                "ask_base_salary": ask_value,
                "trigger": str(entry["trigger"]),
                "concession": str(entry["concession"]),
                "exchange_for": str(entry["exchange_for"]),
                "evidence": str(entry["evidence"]),
            }
        )
    return reindexed


def _normalize_negotiation_objection_playbook(
    raw_playbook: Any,
    *,
    risk_signals: list[dict[str, Any]],
    leverage_signals: list[dict[str, Any]],
    evidence_links: list[dict[str, str]],
    anchor_band: dict[str, Any],
) -> list[dict[str, Any]]:
    severity_rank = {"critical": 3, "high": 2, "medium": 1, "low": 0}
    normalized: list[dict[str, Any]] = []

    if isinstance(raw_playbook, list):
        for raw in raw_playbook:
            if not isinstance(raw, dict):
                continue
            risk_signal = str(raw.get("risk_signal", "")).strip()
            objection = str(raw.get("objection", "")).strip()
            response = str(raw.get("response", "")).strip()
            evidence = str(raw.get("evidence", "")).strip()
            fallback_trade = str(raw.get("fallback_trade", "")).strip()
            if not risk_signal or not objection or not response or not evidence or not fallback_trade:
                continue
            normalized.append(
                {
                    "risk_signal": risk_signal,
                    "objection": objection,
                    "response": response,
                    "evidence": evidence,
                    "fallback_trade": fallback_trade,
                }
            )

    if not normalized:
        ranked_risks = sorted(
            risk_signals,
            key=lambda item: (
                -severity_rank.get(str(item.get("severity", "")).lower(), 0),
                -float(item.get("score", 0.0)),
                str(item.get("signal", "")),
            ),
        )
        if not ranked_risks:
            ranked_risks = [
                {
                    "signal": "timeline_risk",
                    "severity": "medium",
                    "score": 45.0,
                    "evidence": "Offer timeline uncertainty requires active risk management.",
                }
            ]

        for index, risk in enumerate(ranked_risks[:3]):
            leverage = leverage_signals[min(index, len(leverage_signals) - 1)] if leverage_signals else {}
            evidence_link = evidence_links[min(index, len(evidence_links) - 1)] if evidence_links else {}
            signal_label = str(risk.get("signal", "timeline_risk")).replace("_", " ")
            normalized.append(
                {
                    "risk_signal": str(risk.get("signal", "timeline_risk")),
                    "objection": f"We have constraints related to {signal_label}.",
                    "response": (
                        f"Address {signal_label} directly and tie the ask to "
                        f"{str(leverage.get('signal', 'performance momentum')).replace('_', ' ')} outcomes."
                    ),
                    "evidence": (
                        f"{str(risk.get('evidence', '')).strip()} "
                        f"Source {str(evidence_link.get('source_type', 'offer_input'))}:"
                        f"{str(evidence_link.get('source_id', 'candidate'))}."
                    ).strip(),
                    "fallback_trade": (
                        f"If base cannot move, hold floor at {int(anchor_band.get('floor_base_salary', 0))} "
                        "and request non-base upside with timeline guarantees."
                    ),
                }
            )

    return normalized[:3]


def _normalize_negotiation_talking_points(
    raw_points: Any,
    *,
    anchor_band: dict[str, Any],
    leverage_signals: list[dict[str, Any]],
    risk_signals: list[dict[str, Any]],
) -> list[str]:
    if isinstance(raw_points, list):
        normalized: list[str] = []
        for raw in raw_points:
            if not isinstance(raw, str):
                continue
            point = raw.strip()
            if not point:
                continue
            normalized.append(point)
        if normalized:
            return normalized[:5]

    lead_leverage = (
        str(leverage_signals[0].get("signal", "")).replace("_", " ")
        if leverage_signals
        else "performance momentum"
    )
    lead_risk = (
        str(risk_signals[0].get("signal", "")).replace("_", " ")
        if risk_signals
        else "timeline pressure"
    )
    return [
        f"Anchor at {int(anchor_band.get('ceiling_base_salary', 0))} with evidence from {lead_leverage}.",
        (
            f"Protect minimum floor of {int(anchor_band.get('floor_base_salary', 0))} and trade concessions only "
            "for explicit commitments."
        ),
        f"Pre-handle {lead_risk} objections before discussing compensation movement.",
    ]


def _validate_append_interview_response_payload(payload: dict[str, Any]) -> list[dict[str, str]]:
    errors: list[dict[str, str]] = []

    response = payload.get("response")
    if not isinstance(response, str) or not response.strip():
        errors.append({"field": "response", "reason": "must be a non-empty string"})

    question_id = payload.get("question_id")
    if question_id is not None and (not isinstance(question_id, str) or not question_id.strip()):
        errors.append({"field": "question_id", "reason": "must be a non-empty string when provided"})

    expected_version = payload.get("expected_version")
    if expected_version is not None and (
        not isinstance(expected_version, int) or isinstance(expected_version, bool) or expected_version < 1
    ):
        errors.append({"field": "expected_version", "reason": "must be an integer >= 1 when provided"})

    override_followup = payload.get("override_followup")
    if override_followup is not None:
        if not isinstance(override_followup, dict):
            errors.append({"field": "override_followup", "reason": "must be an object when provided"})
        else:
            reviewer_id = override_followup.get("reviewer_id")
            if not isinstance(reviewer_id, str) or not reviewer_id.strip():
                errors.append({"field": "override_followup.reviewer_id", "reason": "must be a non-empty string"})

            reason = override_followup.get("reason")
            if not isinstance(reason, str) or not reason.strip():
                errors.append({"field": "override_followup.reason", "reason": "must be a non-empty string"})

            competency = override_followup.get("competency")
            if not isinstance(competency, str) or not competency.strip():
                errors.append({"field": "override_followup.competency", "reason": "must be a non-empty string"})

            difficulty = override_followup.get("difficulty")
            if difficulty is not None and (
                not isinstance(difficulty, int) or isinstance(difficulty, bool) or difficulty < 1 or difficulty > 5
            ):
                errors.append({"field": "override_followup.difficulty", "reason": "must be an integer between 1 and 5"})

    return errors


def _parse_storybank_query(environ: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, str]]]:
    query_string = str(environ.get("QUERY_STRING", ""))
    query_map = parse_qs(query_string, keep_blank_values=True)
    errors: list[dict[str, str]] = []

    min_quality: float | None = None
    raw_min_quality = _first_query_value(query_map, "min_quality")
    if raw_min_quality is not None:
        try:
            min_quality = float(raw_min_quality)
        except ValueError:
            errors.append({"field": "min_quality", "reason": "must be a number between 0 and 1"})
        else:
            if min_quality < 0 or min_quality > 1:
                errors.append({"field": "min_quality", "reason": "must be between 0 and 1"})

    competency: str | None = None
    raw_competency = _first_query_value(query_map, "competency")
    if raw_competency is not None:
        competency = raw_competency.strip()
        if not competency:
            errors.append({"field": "competency", "reason": "must be a non-empty string when provided"})

    limit = 20
    raw_limit = _first_query_value(query_map, "limit")
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except ValueError:
            errors.append({"field": "limit", "reason": "must be an integer between 1 and 100"})
        else:
            if limit < 1 or limit > 100:
                errors.append({"field": "limit", "reason": "must be an integer between 1 and 100"})

    cursor_offset = 0
    raw_cursor = _first_query_value(query_map, "cursor")
    if raw_cursor is not None:
        try:
            cursor_offset = int(raw_cursor)
        except ValueError:
            errors.append({"field": "cursor", "reason": "must be a non-negative integer offset"})
        else:
            if cursor_offset < 0:
                errors.append({"field": "cursor", "reason": "must be a non-negative integer offset"})

    return {
        "min_quality": min_quality,
        "competency": competency,
        "limit": limit,
        "cursor_offset": cursor_offset,
    }, errors


def _parse_candidate_progress_dashboard_query(environ: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, str]]]:
    query_string = str(environ.get("QUERY_STRING", ""))
    query_map = parse_qs(query_string, keep_blank_values=True)
    errors: list[dict[str, str]] = []

    target_role: str | None = None
    raw_target_role = _first_query_value(query_map, "target_role")
    if raw_target_role is not None:
        target_role = raw_target_role.strip()
        if not target_role:
            errors.append({"field": "target_role", "reason": "must be a non-empty string when provided"})

    return {"target_role": target_role}, errors


def _first_query_value(query_map: dict[str, list[str]], field: str) -> str | None:
    values = query_map.get(field)
    if not values:
        return None
    return values[0]


def _validate_patch_review_payload(payload: dict[str, Any]) -> list[dict[str, str]]:
    errors: list[dict[str, str]] = []

    expected_version = payload.get("expected_version")
    if not isinstance(expected_version, int) or isinstance(expected_version, bool) or expected_version < 1:
        errors.append({"field": "expected_version", "reason": "must be an integer >= 1"})

    patch = payload.get("patch")
    if not isinstance(patch, dict):
        errors.append({"field": "patch", "reason": "must be an object"})

    review_notes = payload.get("review_notes")
    if review_notes is not None and not isinstance(review_notes, str):
        errors.append({"field": "review_notes", "reason": "must be a string when provided"})

    reviewed_by = payload.get("reviewed_by")
    if reviewed_by is not None and not isinstance(reviewed_by, str):
        errors.append({"field": "reviewed_by", "reason": "must be a string when provided"})

    return errors


def _validate_job_spec_patch_object(patch: dict[str, Any]) -> list[dict[str, str]]:
    errors: list[dict[str, str]] = []
    if not patch:
        errors.append({"field": "patch", "reason": "must contain at least one mutable field"})
        return errors

    for field in patch:
        if field in IMMUTABLE_JOB_SPEC_PATCH_FIELDS:
            errors.append({"field": f"patch.{field}", "reason": "field is immutable"})
            continue
        if field not in MUTABLE_JOB_SPEC_PATCH_FIELDS:
            errors.append({"field": f"patch.{field}", "reason": "field is not supported for review patch"})

    return errors


def _apply_job_spec_patch(current_job_spec: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    updated = json.loads(json.dumps(current_job_spec))

    for field, value in patch.items():
        if field not in MUTABLE_JOB_SPEC_PATCH_FIELDS:
            continue

        current_value = updated.get(field)
        if isinstance(current_value, dict) and isinstance(value, dict):
            updated[field] = _deep_merge_dict(current_value, value)
        else:
            updated[field] = value

    return updated


def _deep_merge_dict(base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    merged: dict[str, Any] = dict(base)
    for key, value in patch.items():
        if isinstance(merged.get(key), dict) and isinstance(value, dict):
            merged[key] = _deep_merge_dict(merged[key], value)
        else:
            merged[key] = value
    return merged


def _status_payload(record: JobIngestionRecord) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "ingestion_id": record.ingestion_id,
        "status": record.status,
        "current_stage": record.current_stage,
    }

    if record.progress_pct is not None:
        payload["progress_pct"] = record.progress_pct

    if record.result_job_spec_id:
        payload["result"] = {"entity_id": record.result_job_spec_id}

    if record.error_code and record.error_message and record.error_retryable is not None:
        error_payload: dict[str, Any] = {
            "code": record.error_code,
            "message": record.error_message,
            "retryable": record.error_retryable,
        }
        if record.error_details:
            error_payload["details"] = record.error_details
        payload["error"] = error_payload

    return payload


def _candidate_status_payload(record: CandidateIngestionRecord) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "ingestion_id": record.ingestion_id,
        "status": record.status,
        "current_stage": record.current_stage,
    }

    if record.progress_pct is not None:
        payload["progress_pct"] = record.progress_pct

    if record.result_candidate_id:
        payload["result"] = {"entity_id": record.result_candidate_id}

    if record.error_code and record.error_message and record.error_retryable is not None:
        error_payload: dict[str, Any] = {
            "code": record.error_code,
            "message": record.error_message,
            "retryable": record.error_retryable,
        }
        if record.error_details:
            error_payload["details"] = record.error_details
        payload["error"] = error_payload

    return payload


def _normalize_progress_competency_trends(raw_trends: Any) -> list[dict[str, Any]]:
    if not isinstance(raw_trends, list):
        return []

    normalized: list[dict[str, Any]] = []
    for raw_entry in raw_trends:
        if not isinstance(raw_entry, dict):
            continue
        competency = str(raw_entry.get("competency", "")).strip()
        if not competency:
            continue

        baseline_score = _coerce_dashboard_score(raw_entry.get("baseline_score"))
        current_score = _coerce_dashboard_score(raw_entry.get("current_score"))
        delta_score = _coerce_dashboard_delta(raw_entry.get("delta_score"))
        if baseline_score is None or current_score is None or delta_score is None:
            continue

        observation_count = _coerce_dashboard_count(raw_entry.get("observation_count"))
        normalized.append(
            {
                "competency": competency,
                "baseline_score": baseline_score,
                "current_score": current_score,
                "delta_score": delta_score,
                "observation_count": observation_count,
                "trend_direction": _trend_direction_from_delta(delta_score),
            }
        )

    return normalized


def _build_top_improving_competency_cards(competency_trends: list[dict[str, Any]]) -> list[dict[str, Any]]:
    improving = [entry for entry in competency_trends if float(entry.get("delta_score", 0.0)) > 0.0]
    improving.sort(key=lambda entry: (-float(entry["delta_score"]), str(entry["competency"])))
    return improving[:3]


def _build_top_risk_competency_cards(competency_trends: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ranked = sorted(
        competency_trends,
        key=lambda entry: (
            float(entry["current_score"]),
            float(entry["delta_score"]),
            str(entry["competency"]),
        ),
    )
    return ranked[:3]


def _latest_trajectory_plan_dashboard_metadata(latest_trajectory_plan: dict[str, Any] | None) -> dict[str, Any]:
    metadata: dict[str, Any] = {"available": False}
    if not isinstance(latest_trajectory_plan, dict):
        return metadata

    trajectory_plan_id = str(latest_trajectory_plan.get("trajectory_plan_id", "")).strip()
    target_role = str(latest_trajectory_plan.get("target_role", "")).strip()
    if not trajectory_plan_id or not target_role:
        return metadata

    metadata["available"] = True
    metadata["trajectory_plan_id"] = trajectory_plan_id
    metadata["target_role"] = target_role

    raw_version = latest_trajectory_plan.get("version")
    if isinstance(raw_version, int) and not isinstance(raw_version, bool) and raw_version >= 1:
        metadata["version"] = raw_version

    supersedes_id = latest_trajectory_plan.get("supersedes_trajectory_plan_id")
    if isinstance(supersedes_id, str) and supersedes_id.strip():
        metadata["supersedes_trajectory_plan_id"] = supersedes_id.strip()

    generated_at = latest_trajectory_plan.get("generated_at")
    if isinstance(generated_at, str) and generated_at.strip():
        metadata["generated_at"] = generated_at.strip()

    role_readiness_score = _coerce_dashboard_score(latest_trajectory_plan.get("role_readiness_score"))
    if role_readiness_score is not None:
        metadata["role_readiness_score"] = role_readiness_score

    horizon_months = latest_trajectory_plan.get("horizon_months")
    if isinstance(horizon_months, int) and not isinstance(horizon_months, bool) and 1 <= horizon_months <= 24:
        metadata["horizon_months"] = horizon_months

    return metadata


def _build_dashboard_readiness_signals(
    *,
    progress_summary: dict[str, Any],
    latest_trajectory_metadata: dict[str, Any],
) -> dict[str, Any]:
    history_counts = progress_summary.get("history_counts")
    snapshot_count = 0
    if isinstance(history_counts, dict):
        snapshot_count = _coerce_dashboard_count(history_counts.get("snapshots"))

    current_score: float | None = None
    current = progress_summary.get("current")
    if isinstance(current, dict):
        current_score = _coerce_dashboard_score(current.get("overall_score"))

    overall_delta_score: float | None = None
    delta = progress_summary.get("delta")
    if isinstance(delta, dict):
        overall_delta_score = _coerce_dashboard_delta(delta.get("overall_score"))

    trajectory_readiness_score: float | None = None
    if isinstance(latest_trajectory_metadata, dict):
        trajectory_readiness_score = _coerce_dashboard_score(latest_trajectory_metadata.get("role_readiness_score"))

    resolved_readiness_score = trajectory_readiness_score if trajectory_readiness_score is not None else current_score
    readiness_signals: dict[str, Any] = {
        "snapshot_count": snapshot_count,
        "readiness_band": _readiness_band_for_score(resolved_readiness_score),
        "momentum": _momentum_signal_from_delta(overall_delta_score),
    }

    if current_score is not None:
        readiness_signals["overall_score"] = current_score
    if overall_delta_score is not None:
        readiness_signals["overall_delta_score"] = overall_delta_score
    if trajectory_readiness_score is not None:
        readiness_signals["trajectory_readiness_score"] = trajectory_readiness_score

    return readiness_signals


def _readiness_band_for_score(score: float | None) -> str:
    if score is None:
        return "insufficient_data"
    if score >= 80.0:
        return "strong"
    if score >= 65.0:
        return "developing"
    return "at_risk"


def _momentum_signal_from_delta(delta_score: float | None) -> str:
    if delta_score is None:
        return "unknown"
    if delta_score >= 5.0:
        return "improving"
    if delta_score <= -5.0:
        return "declining"
    return "stable"


def _trend_direction_from_delta(delta_score: float) -> str:
    if delta_score > 0:
        return "improving"
    if delta_score < 0:
        return "declining"
    return "flat"


def _coerce_dashboard_score(raw_value: Any) -> float | None:
    if not isinstance(raw_value, (int, float)) or isinstance(raw_value, bool):
        return None
    return round(max(0.0, min(100.0, float(raw_value))), 2)


def _coerce_dashboard_delta(raw_value: Any) -> float | None:
    if not isinstance(raw_value, (int, float)) or isinstance(raw_value, bool):
        return None
    return round(max(-100.0, min(100.0, float(raw_value))), 2)


def _coerce_dashboard_count(raw_value: Any) -> int:
    if not isinstance(raw_value, int) or isinstance(raw_value, bool):
        return 0
    return max(0, raw_value)


def _sections_by_id(sections: tuple[Any, ...]) -> dict[str, list[str]]:
    grouped: dict[str, list[str]] = {}
    for section in sections:
        section_id = str(getattr(section, "section_id", "")).strip()
        lines = getattr(section, "lines", ())
        if not section_id:
            continue
        clean_lines = [_clean_line(str(line)) for line in lines if _clean_line(str(line))]
        if clean_lines:
            grouped.setdefault(section_id, []).extend(clean_lines)
    return grouped


def _collect_lines(sections: dict[str, list[str]], *, preferred_keys: tuple[str, ...]) -> list[str]:
    combined: list[str] = []
    for key in preferred_keys:
        combined.extend(sections.get(key, []))
    return _unique_preserving_order(combined)


def _clean_line(value: str) -> str:
    line = value.strip()
    line = re.sub(r"^[-*]\s*", "", line)
    return line.strip()


def _extract_skill_terms(lines: list[str], normalizer: Any) -> list[str]:
    alias_map = getattr(normalizer, "_alias_to_canonical", {})
    aliases = sorted([alias for alias in alias_map if isinstance(alias, str) and alias], key=len, reverse=True)

    matched: list[str] = []
    for line in lines:
        normalized_line = unicodedata.normalize("NFKD", line)
        normalized_line = normalized_line.encode("ascii", "ignore").decode("ascii")
        normalized_line = re.sub(r"[^a-z0-9\s]+", " ", normalized_line.lower())
        normalized_line = re.sub(r"\s+", " ", normalized_line).strip()
        for alias in aliases:
            if re.search(rf"(^|\s){re.escape(alias)}(\s|$)", normalized_line):
                matched.append(alias)

    if matched:
        return _unique_preserving_order(matched)

    fallback_terms: list[str] = []
    for line in lines:
        parts = re.split(r",|/|\band\b", line, flags=re.IGNORECASE)
        for part in parts:
            cleaned = _clean_line(part)
            if cleaned:
                normalized = unicodedata.normalize("NFKD", cleaned)
                normalized = normalized.encode("ascii", "ignore").decode("ascii")
                normalized = re.sub(r"[^a-z0-9\s]+", " ", normalized.lower())
                normalized = re.sub(r"\s+", " ", normalized).strip()
                words = normalized.split()
                if not words:
                    continue
                if normalized in {
                    "hvem er du",
                    "vi forestiller os",
                    "du er ikke nodvendigvis udvikler men du",
                }:
                    continue
                if len(words) > 3:
                    continue
                if "og" in words and len(words) > 2:
                    continue
                fallback_terms.append(cleaned)

    return _unique_preserving_order(fallback_terms)


def _normalized_term_labels(normalized_terms: tuple[Any, ...]) -> list[str]:
    labels: list[str] = []
    for term in normalized_terms:
        is_known = bool(getattr(term, "is_known", False))
        if is_known:
            label = str(getattr(term, "canonical_label", "")).strip()
        else:
            label = str(getattr(term, "input_term", "")).strip()
        if label:
            labels.append(label)
    return _unique_preserving_order(labels)


def _competency_weights(required_terms: tuple[Any, ...], preferred_terms: tuple[Any, ...]) -> dict[str, float]:
    weights: dict[str, float] = {}

    for term in required_terms:
        canonical_id = str(getattr(term, "canonical_id", "")).strip()
        is_known = bool(getattr(term, "is_known", False))
        if not canonical_id:
            continue
        if is_known:
            weights[canonical_id] = 1.0
        elif canonical_id.startswith("skill.freeform."):
            weights[canonical_id] = max(weights.get(canonical_id, 0.0), 0.55)

    for term in preferred_terms:
        canonical_id = str(getattr(term, "canonical_id", "")).strip()
        is_known = bool(getattr(term, "is_known", False))
        if not canonical_id:
            continue
        if is_known:
            weights[canonical_id] = max(weights.get(canonical_id, 0.0), 0.65)
        elif canonical_id.startswith("skill.freeform."):
            weights[canonical_id] = max(weights.get(canonical_id, 0.0), 0.4)

    return weights


def _resolve_job_required_competency_weights(*, job_spec: dict[str, Any], taxonomy_normalizer: Any) -> dict[str, float]:
    resolved: dict[str, float] = {}

    raw_weights = job_spec.get("competency_weights")
    if isinstance(raw_weights, dict):
        for raw_key, raw_value in raw_weights.items():
            competency_id = str(raw_key).strip()
            if not competency_id:
                continue
            if not isinstance(raw_value, (int, float)) or isinstance(raw_value, bool):
                continue
            resolved[competency_id] = max(0.0, min(1.0, float(raw_value)))

    requirements = job_spec.get("requirements")
    if not isinstance(requirements, dict):
        return resolved

    required_skills = requirements.get("required_skills")
    if isinstance(required_skills, list):
        for value in required_skills:
            if not isinstance(value, str) or not value.strip():
                continue
            normalized = taxonomy_normalizer.normalize_term(value)
            competency_id = str(getattr(normalized, "canonical_id", "")).strip()
            if not competency_id:
                continue
            default_weight = 1.0 if bool(getattr(normalized, "is_known", False)) else 0.55
            resolved[competency_id] = max(resolved.get(competency_id, 0.0), default_weight)

    preferred_skills = requirements.get("preferred_skills")
    if isinstance(preferred_skills, list):
        for value in preferred_skills:
            if not isinstance(value, str) or not value.strip():
                continue
            normalized = taxonomy_normalizer.normalize_term(value)
            competency_id = str(getattr(normalized, "canonical_id", "")).strip()
            if not competency_id:
                continue
            default_weight = 0.65 if bool(getattr(normalized, "is_known", False)) else 0.4
            resolved[competency_id] = max(resolved.get(competency_id, 0.0), default_weight)

    return resolved


def _resolve_candidate_competency_scores(*, candidate_profile: dict[str, Any], taxonomy_normalizer: Any) -> dict[str, float]:
    raw_skills = candidate_profile.get("skills")
    if not isinstance(raw_skills, dict):
        return {}

    resolved: dict[str, float] = {}
    for raw_skill, raw_score in raw_skills.items():
        if not isinstance(raw_score, (int, float)) or isinstance(raw_score, bool):
            continue
        skill_key = str(raw_skill).strip()
        if not skill_key:
            continue

        competency_id: str
        if skill_key.startswith("skill."):
            competency_id = skill_key
        else:
            normalized = taxonomy_normalizer.normalize_term(skill_key.replace("_", " "))
            competency_id = str(getattr(normalized, "canonical_id", "")).strip()
            if not competency_id:
                continue

        score = max(0.0, min(1.0, float(raw_score)))
        resolved[competency_id] = max(resolved.get(competency_id, 0.0), score)

    return resolved


def _build_evidence_spans(
    *,
    responsibilities: list[str],
    required_terms: tuple[Any, ...],
    preferred_terms: tuple[Any, ...],
) -> list[dict[str, Any]]:
    evidence_spans: list[dict[str, Any]] = []

    for idx, text in enumerate(responsibilities):
        evidence_spans.append(
            {
                "field": f"responsibilities[{idx}]",
                "text": text,
                "confidence": 0.85,
            }
        )

    for idx, term in enumerate(required_terms):
        label = str(getattr(term, "canonical_label", "") or getattr(term, "input_term", "")).strip()
        if not label:
            continue
        confidence = 0.95 if bool(getattr(term, "is_known", False)) else 0.5
        evidence_spans.append(
            {
                "field": f"requirements.required_skills[{idx}]",
                "text": label,
                "confidence": confidence,
            }
        )

    for idx, term in enumerate(preferred_terms):
        label = str(getattr(term, "canonical_label", "") or getattr(term, "input_term", "")).strip()
        if not label:
            continue
        confidence = 0.8 if bool(getattr(term, "is_known", False)) else 0.45
        evidence_spans.append(
            {
                "field": f"requirements.preferred_skills[{idx}]",
                "text": label,
                "confidence": confidence,
            }
        )

    return evidence_spans


def _extraction_confidence(evidence_spans: list[dict[str, Any]]) -> float:
    if not evidence_spans:
        return 0.5

    score = sum(float(span["confidence"]) for span in evidence_spans) / len(evidence_spans)
    score = max(0.0, min(1.0, score))
    return round(score, 3)


def _unique_preserving_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            ordered.append(value)
    return ordered


def _followup_question_text(competency: str) -> str:
    label = competency.replace("skill.", "").replace("_", " ").strip()
    if not label:
        label = "execution"
    return f"What tradeoffs did you make while applying {label}, and what was the outcome?"


def _apply_interview_response_to_session(
    current_session: dict[str, Any],
    payload: dict[str, Any],
    *,
    followup_selector: Any,
) -> tuple[dict[str, Any], str, float]:
    updated = json.loads(json.dumps(current_session))
    questions_raw = updated.get("questions")
    if not isinstance(questions_raw, list) or not questions_raw:
        raise ValueError("Interview session has no questions to answer")

    response_text = str(payload["response"]).strip()
    requested_question_id = payload.get("question_id")
    target_index = -1

    if isinstance(requested_question_id, str) and requested_question_id.strip():
        normalized_question_id = requested_question_id.strip()
        for idx, question in enumerate(questions_raw):
            if str(question.get("question_id", "")).strip() == normalized_question_id:
                target_index = idx
                break
        if target_index < 0:
            raise ValueError("question_id does not exist in interview session")
    else:
        for idx, question in enumerate(questions_raw):
            if not str(question.get("response", "")).strip():
                target_index = idx
                break
        if target_index < 0:
            target_index = len(questions_raw) - 1

    question = questions_raw[target_index]
    question_id = str(question.get("question_id", "")).strip()
    difficulty = int(question.get("difficulty", 1))
    score = _score_interview_response(response_text=response_text, difficulty=difficulty)
    question["response"] = response_text
    question["score"] = score

    scores_map, overall_score = _recompute_interview_scores(questions_raw)
    updated["scores"] = scores_map
    updated["overall_score"] = overall_score
    updated["root_cause_tags"] = sorted([competency for competency, value in scores_map.items() if float(value) < 60.0])

    has_unanswered = any(not str(item.get("response", "")).strip() for item in questions_raw)
    if not has_unanswered and len(questions_raw) < 5:
        followup_decision = followup_selector.select_followup(
            questions=questions_raw,
            scores=scores_map,
            last_question=question,
            last_score=score,
        )
        next_competency = str(followup_decision.get("competency", "execution"))
        next_difficulty = int(followup_decision.get("difficulty", max(1, min(5, difficulty + 1))))
        next_difficulty = max(1, min(5, next_difficulty))
        selection_reason = str(followup_decision.get("reason", "coverage_gap")).strip() or "coverage_gap"
        ranking_position = int(followup_decision.get("ranking_position", len(questions_raw) + 1))
        deterministic_confidence = float(followup_decision.get("confidence", 0.62))
        override_followup = payload.get("override_followup")
        override_applied = False
        override_reviewer_id = ""
        override_reason = ""
        override_trigger_confidence = round(max(0.0, min(1.0, deterministic_confidence)), 3)

        if (
            isinstance(override_followup, dict)
            and deterministic_confidence < FOLLOWUP_OVERRIDE_CONFIDENCE_THRESHOLD
        ):
            override_competency = str(override_followup.get("competency", "")).strip()
            if override_competency:
                next_competency = override_competency
                selection_reason = "reviewer_override"
                override_applied = True
                override_reviewer_id = str(override_followup.get("reviewer_id", "")).strip()
                override_reason = str(override_followup.get("reason", "")).strip()
                override_difficulty = override_followup.get("difficulty")
                if isinstance(override_difficulty, int) and not isinstance(override_difficulty, bool):
                    next_difficulty = max(1, min(5, int(override_difficulty)))
                raw_override_ranking = override_followup.get("ranking_position", ranking_position)
                try:
                    ranking_position = int(raw_override_ranking)
                except (TypeError, ValueError):
                    ranking_position = ranking_position
                ranking_position = max(1, ranking_position)

        followup_question_id = f"q_{len(questions_raw) + 1}"
        followup_question = {
            "question_id": followup_question_id,
            "text": _followup_question_text(next_competency),
            "competency": next_competency,
            "difficulty": next_difficulty,
            "response": "",
            "score": 0.0,
            "planner_metadata": {
                "source_competency": next_competency,
                "ranking_position": ranking_position,
                "deterministic_confidence": round(max(0.5, min(0.99, deterministic_confidence)), 3),
                "selection_reason": selection_reason,
                "trigger_question_id": question_id,
                "trigger_score": score,
                "override_applied": override_applied,
                "override_reviewer_id": override_reviewer_id,
                "override_reason": override_reason,
                "override_trigger_confidence": override_trigger_confidence,
            },
        }
        questions_raw.append(followup_question)
        follow_up_ids = question.get("follow_up_ids")
        if isinstance(follow_up_ids, list):
            follow_up_ids.append(followup_question_id)
        else:
            question["follow_up_ids"] = [followup_question_id]
        has_unanswered = True

    updated["status"] = "in_progress" if has_unanswered else "completed"
    updated["version"] = int(current_session.get("version", 1)) + 1
    return updated, question_id, score


def _recompute_interview_scores(questions: list[dict[str, Any]]) -> tuple[dict[str, float], float]:
    by_competency: dict[str, list[float]] = {}
    for question in questions:
        response_text = str(question.get("response", "")).strip()
        if not response_text:
            continue
        competency = str(question.get("competency", "")).strip()
        if not competency:
            continue
        score_value = float(question.get("score", 0.0))
        by_competency.setdefault(competency, []).append(score_value)

    scores = {
        competency: round(sum(values) / len(values), 2)
        for competency, values in by_competency.items()
        if values
    }
    flattened = [score for values in by_competency.values() for score in values]
    overall = round(sum(flattened) / len(flattened), 2) if flattened else 0.0
    return scores, overall


def _score_interview_response(*, response_text: str, difficulty: int) -> float:
    words = [part for part in response_text.split() if part]
    word_count = len(words)
    has_metric = bool(re.search(r"\b\d+(\.\d+)?%?\b", response_text))
    has_action_signal = bool(
        re.search(r"\b(led|built|implemented|optimized|reduced|improved|shipped|designed)\b", response_text, re.IGNORECASE)
    )

    raw_score = 35.0
    raw_score += min(word_count, 90) * 0.45
    raw_score += 12.0 if has_metric else 0.0
    raw_score += 8.0 if has_action_signal else 0.0
    raw_score += max(1, min(5, difficulty)) * 2.0
    return round(max(0.0, min(100.0, raw_score)), 2)


def _safe_score(value: Any) -> float:
    try:
        score = float(value)
    except (TypeError, ValueError):
        return 0.0
    if score != score:
        return 0.0
    return max(0.0, min(100.0, score))


def _aggregate_feedback_scores(session: dict[str, Any]) -> tuple[dict[str, float], float]:
    by_competency: dict[str, list[float]] = {}
    questions = session.get("questions")
    if isinstance(questions, list):
        for question in questions:
            if not isinstance(question, dict):
                continue
            competency = str(question.get("competency", "")).strip()
            if not competency:
                continue
            by_competency.setdefault(competency, []).append(_safe_score(question.get("score")))

    if by_competency:
        aggregated: dict[str, float] = {}
        for competency in sorted(by_competency):
            score_history = by_competency[competency]
            mean_score = sum(score_history) / len(score_history)
            trend_adjustment = 0.0
            if len(score_history) >= 2:
                trend_adjustment = (score_history[-1] - score_history[0]) * 0.15
                trend_adjustment = max(-8.0, min(8.0, trend_adjustment))

            aggregated_score = max(0.0, min(100.0, mean_score + trend_adjustment))
            aggregated[competency] = round(aggregated_score, 2)

        overall = round(sum(aggregated.values()) / len(aggregated), 2) if aggregated else 0.0
        return aggregated, overall

    raw_scores = session.get("scores")
    normalized: dict[str, float] = {}
    if isinstance(raw_scores, dict):
        for competency, raw_score in sorted(raw_scores.items(), key=lambda item: str(item[0])):
            if not isinstance(competency, str) or not competency.strip():
                continue
            normalized[competency] = round(_safe_score(raw_score), 2)
        if normalized:
            overall = round(sum(normalized.values()) / len(normalized), 2)
            return normalized, overall

    return {}, round(_safe_score(session.get("overall_score")), 2)


def _feedback_competency_scores(session: dict[str, Any]) -> dict[str, float]:
    scores, _ = _aggregate_feedback_scores(session)
    return scores


def _feedback_top_gaps(*, session: dict[str, Any], competency_scores: dict[str, float]) -> list[dict[str, str]]:
    quality_signals = _feedback_quality_signals(session)
    ranked_with_risk: list[tuple[str, float, float]] = []
    for competency, score in competency_scores.items():
        signal = quality_signals.get(competency, {})
        risk_score = _feedback_gap_risk_score(score=float(score), signals=signal)
        ranked_with_risk.append((competency, float(score), risk_score))

    ranked_with_risk.sort(key=lambda item: (item[2], item[1], item[0]))
    if not ranked_with_risk:
        root_cause_tags = sorted(
            {
                str(item).strip()
                for item in session.get("root_cause_tags", [])
                if isinstance(item, str) and str(item).strip()
            }
        )
        ranked_with_risk = [(tag, 55.0, 55.0) for tag in root_cause_tags]
    if not ranked_with_risk:
        fallback = _safe_score(session.get("overall_score"))
        fallback_score = fallback if fallback > 0 else 55.0
        ranked_with_risk = [("overall_performance", fallback_score, fallback_score)]

    top_gaps: list[dict[str, str]] = []
    for competency, score, _ in ranked_with_risk[:3]:
        signal = quality_signals.get(competency, {})
        top_gaps.append(
            {
                "gap": _feedback_gap_label(competency),
                "severity": _feedback_severity(score=score, signals=signal),
                "root_cause": _feedback_root_cause(score=score, signals=signal),
                "evidence": _feedback_gap_evidence(session=session, competency=competency),
            }
        )
    return top_gaps


def _feedback_gap_label(competency: str) -> str:
    label = competency.replace("skill.", "").replace("_", " ").strip()
    if not label:
        return "Overall Interview Performance"
    return label.title()


def _feedback_severity(*, score: float, signals: dict[str, float]) -> str:
    adjusted_score = _feedback_gap_risk_score(score=score, signals=signals)
    if adjusted_score < 50.0:
        return "critical"
    if adjusted_score < 65.0:
        return "high"
    if adjusted_score < 80.0:
        return "medium"
    return "low"


def _feedback_root_cause(*, score: float, signals: dict[str, float]) -> str:
    answered_count = int(signals.get("answered_count", 0))
    if answered_count <= 0:
        return "Responses were missing for this competency, so signal quality could not be established."

    metric_ratio = float(signals.get("metric_ratio", 0.0))
    action_ratio = float(signals.get("action_ratio", 0.0))
    avg_words = float(signals.get("avg_words", 0.0))
    low_score_ratio = float(signals.get("low_score_ratio", 0.0))
    trend_delta = float(signals.get("trend_delta", 0.0))

    if metric_ratio < 0.34 and avg_words < 16.0:
        return "Responses were brief and lacked quantified outcomes."
    if metric_ratio < 0.34:
        return "Responses lacked quantified outcomes to demonstrate impact."
    if action_ratio < 0.5:
        return "Responses did not clearly communicate ownership and actions."
    if avg_words < 16.0:
        return "Responses were too brief to demonstrate structured depth."
    if low_score_ratio >= 0.5 and trend_delta <= -10.0:
        return "Scores declined across follow-ups, indicating inconsistent response depth."
    if low_score_ratio >= 0.5:
        return "Multiple turns stayed below rubric expectations for this competency."

    if score < 50.0:
        return "Responses lacked enough specificity and measurable outcomes."
    if score < 65.0:
        return "Examples showed partial depth but did not fully demonstrate impact."
    if score < 80.0:
        return "Signal is promising but consistency and structure need improvement."
    return "Maintain this area while improving adjacent competencies."


def _feedback_gap_evidence(*, session: dict[str, Any], competency: str) -> str:
    questions = session.get("questions")
    response_candidates: list[tuple[float, str, str]] = []
    if isinstance(questions, list):
        for question in questions:
            if not isinstance(question, dict):
                continue
            question_competency = str(question.get("competency", "")).strip()
            response_text = str(question.get("response", "")).strip()
            if question_competency != competency or not response_text:
                continue
            question_id = str(question.get("question_id", "question")).strip() or "question"
            score = _safe_score(question.get("score"))
            snippet = response_text if len(response_text) <= 140 else f"{response_text[:137]}..."
            response_candidates.append((score, question_id, snippet))
    if response_candidates:
        best = sorted(response_candidates, key=lambda item: (item[0], item[1]))[0]
        return f"{best[1]} (score={best[0]:.1f}): {best[2]}"
    return "No response evidence captured for this competency yet."


def _feedback_quality_signals(session: dict[str, Any]) -> dict[str, dict[str, float]]:
    raw: dict[str, dict[str, Any]] = {}
    questions = session.get("questions")
    if not isinstance(questions, list):
        return {}

    for question in questions:
        if not isinstance(question, dict):
            continue
        competency = str(question.get("competency", "")).strip()
        if not competency:
            continue

        signal = raw.setdefault(
            competency,
            {
                "question_count": 0,
                "answered_count": 0,
                "score_total": 0.0,
                "low_score_count": 0,
                "metric_count": 0,
                "action_count": 0,
                "word_total": 0,
                "first_score": None,
                "last_score": None,
            },
        )

        score = _safe_score(question.get("score"))
        signal["question_count"] += 1
        signal["score_total"] += score
        if signal["first_score"] is None:
            signal["first_score"] = score
        signal["last_score"] = score
        if score < 60.0:
            signal["low_score_count"] += 1

        response_text = str(question.get("response", "")).strip()
        if not response_text:
            continue

        signal["answered_count"] += 1
        words = [part for part in response_text.split() if part]
        signal["word_total"] += len(words)
        if _has_metric_signal(response_text):
            signal["metric_count"] += 1
        if _has_action_signal(response_text):
            signal["action_count"] += 1

    normalized: dict[str, dict[str, float]] = {}
    for competency, signal in raw.items():
        question_count = max(1, int(signal["question_count"]))
        answered_count = int(signal["answered_count"])
        avg_words = float(signal["word_total"]) / answered_count if answered_count > 0 else 0.0
        metric_ratio = float(signal["metric_count"]) / answered_count if answered_count > 0 else 0.0
        action_ratio = float(signal["action_count"]) / answered_count if answered_count > 0 else 0.0
        low_score_ratio = float(signal["low_score_count"]) / question_count
        trend_delta = 0.0
        if signal["first_score"] is not None and signal["last_score"] is not None:
            trend_delta = float(signal["last_score"]) - float(signal["first_score"])

        normalized[competency] = {
            "question_count": float(question_count),
            "answered_count": float(answered_count),
            "avg_words": round(avg_words, 2),
            "metric_ratio": round(metric_ratio, 3),
            "action_ratio": round(action_ratio, 3),
            "low_score_ratio": round(low_score_ratio, 3),
            "trend_delta": round(trend_delta, 2),
        }

    return normalized


def _feedback_gap_risk_score(*, score: float, signals: dict[str, float]) -> float:
    adjusted_score = _safe_score(score)
    answered_count = int(signals.get("answered_count", 0))
    metric_ratio = float(signals.get("metric_ratio", 0.0))
    action_ratio = float(signals.get("action_ratio", 0.0))
    avg_words = float(signals.get("avg_words", 0.0))
    low_score_ratio = float(signals.get("low_score_ratio", 0.0))
    trend_delta = float(signals.get("trend_delta", 0.0))

    if answered_count <= 0:
        adjusted_score = min(adjusted_score, 45.0)
    else:
        if metric_ratio < 0.34:
            adjusted_score -= 6.0
        if action_ratio < 0.5:
            adjusted_score -= 4.0
        if avg_words < 16.0:
            adjusted_score -= 7.0
        if low_score_ratio >= 0.5:
            adjusted_score -= 6.0
        if trend_delta <= -10.0:
            adjusted_score -= 4.0

    return round(max(0.0, min(100.0, adjusted_score)), 2)


def _has_metric_signal(value: str) -> bool:
    return bool(re.search(r"\b\d+(\.\d+)?%?\b", value))


def _has_action_signal(value: str) -> bool:
    return bool(
        re.search(
            r"\b(led|built|implemented|optimized|reduced|improved|shipped|designed|coordinated|resolved)\b",
            value,
            re.IGNORECASE,
        )
    )


def _feedback_action_plan(top_gaps: list[dict[str, str]]) -> list[dict[str, Any]]:
    focus_areas = [
        str(item.get("gap", "")).strip().lower()
        for item in top_gaps
        if isinstance(item, dict) and str(item.get("gap", "")).strip()
    ]
    if not focus_areas:
        focus_areas = ["overall interview performance"]

    action_plan: list[dict[str, Any]] = []
    for day in range(1, 31):
        focus = focus_areas[(day - 1) % len(focus_areas)]
        if day <= 7:
            phase = "foundation"
            task = f"Draft one STAR outline for {focus} with a clear baseline and target metric."
            success_metric = "Includes Situation, Task, Action, and a quantified Result in <= 6 bullet points."
        elif day <= 14:
            phase = "depth"
            task = f"Record a 2-minute answer for {focus} and revise weak transitions or missing ownership."
            success_metric = "Delivers a coherent 2-minute answer with explicit ownership and one metric."
        elif day <= 21:
            phase = "simulation"
            task = f"Run a timed mock question on {focus} and add one follow-up-ready detail."
            success_metric = "Mock score improves by at least 5 points versus previous {focus} attempt."
        else:
            phase = "stabilization"
            task = f"Run mixed competency rehearsal while prioritizing {focus} under time pressure."
            success_metric = "Maintains >= 70 score quality for {focus} across two consecutive rehearsals."

        action_plan.append(
            {
                "day": day,
                "task": f"[{phase}] {task}",
                "success_metric": success_metric,
            }
        )

    return action_plan


def _feedback_answer_rewrites(*, session: dict[str, Any], top_gaps: list[dict[str, str]]) -> list[str]:
    focus_areas = [
        str(item.get("gap", "")).strip()
        for item in top_gaps
        if isinstance(item, dict) and str(item.get("gap", "")).strip()
    ]
    if not focus_areas:
        focus_areas = ["Overall Interview Performance"]

    candidates = _feedback_low_response_candidates(session=session, limit=3)
    rewrites: list[str] = []

    for idx, candidate in enumerate(candidates):
        focus = focus_areas[idx % len(focus_areas)]
        rewrites.append(
            (
                f"Rewrite {candidate['question_id']} for {focus}: "
                "Situation: summarize context in one sentence. "
                "Task: state your ownership and target. "
                "Action: describe 2 concrete steps you led. "
                "Result: include at least one metric and business impact."
            )
        )

    if rewrites:
        return rewrites

    for focus in focus_areas[:3]:
        rewrites.append(
            (
                f"Rewrite for {focus}: Situation: define context. Task: clarify your role. "
                "Action: describe concrete decisions and tradeoffs. Result: quantify the outcome."
            )
        )
    return rewrites


def _feedback_low_response_candidates(*, session: dict[str, Any], limit: int) -> list[dict[str, Any]]:
    questions = session.get("questions")
    if not isinstance(questions, list):
        return []

    candidates: list[dict[str, Any]] = []
    for question in questions:
        if not isinstance(question, dict):
            continue
        response_text = str(question.get("response", "")).strip()
        if not response_text:
            continue
        question_id = str(question.get("question_id", "question")).strip() or "question"
        score = _safe_score(question.get("score"))
        candidates.append(
            {
                "question_id": question_id,
                "response": response_text,
                "score": score,
            }
        )

    candidates.sort(key=lambda item: (float(item["score"]), str(item["question_id"])))
    return candidates[: max(0, int(limit))]


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _request_id(environ: dict[str, Any]) -> str:
    header_value = str(environ.get("HTTP_X_REQUEST_ID", "")).strip()
    return header_value or f"req_{uuid4().hex}"


def _meta(request_id: str) -> dict[str, str]:
    return {
        "request_id": request_id,
        "timestamp": _utc_timestamp(),
    }


def _success_envelope(*, request_id: str, data: dict[str, Any]) -> dict[str, Any]:
    return {
        "data": data,
        "meta": _meta(request_id),
        "error": None,
    }


def _error_envelope(
    *,
    request_id: str,
    code: str,
    message: str,
    retryable: bool,
    details: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    error_payload: dict[str, Any] = {
        "code": code,
        "message": message,
        "retryable": retryable,
    }
    if details:
        error_payload["details"] = details

    return {
        "data": None,
        "meta": _meta(request_id),
        "error": error_payload,
    }


def _json_response(
    start_response: Any,
    status: HTTPStatus,
    payload: dict[str, Any],
    headers: list[tuple[str, str]] | None = None,
) -> list[bytes]:
    body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")

    response_headers = [
        ("Content-Type", "application/json; charset=utf-8"),
        ("Content-Length", str(len(body))),
    ]
    if headers:
        response_headers.extend(headers)

    start_response(f"{status.value} {status.phrase}", response_headers)
    return [body]
