from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from http import HTTPStatus
from pathlib import Path
from typing import Any
from urllib.parse import unquote
from uuid import uuid4

from .repository import JobIngestionRecord, SQLiteJobIngestionRepository

SOURCE_TYPE_VALUES = {"url", "text", "document_ref"}


class JobIngestionAPI:
    def __init__(self, repository: SQLiteJobIngestionRepository) -> None:
        self._repository = repository

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


def create_app(db_path: str | Path | None = None) -> JobIngestionAPI:
    resolved_db_path = db_path or os.environ.get("JOBCOACH_DB_PATH") or ".tmp/migrate-local.sqlite3"
    return JobIngestionAPI(repository=SQLiteJobIngestionRepository(resolved_db_path))


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


def _request_id(environ: dict[str, Any]) -> str:
    header_value = str(environ.get("HTTP_X_REQUEST_ID", "")).strip()
    return header_value or f"req_{uuid4().hex}"


def _meta(request_id: str) -> dict[str, str]:
    timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    return {
        "request_id": request_id,
        "timestamp": timestamp,
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
