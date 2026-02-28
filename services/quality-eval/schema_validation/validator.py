from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from packages.contracts.artifacts import CORE_SCHEMAS_PATH
from typing import Any, Mapping
DEFAULT_SCHEMA_PATH = CORE_SCHEMAS_PATH


@dataclass(frozen=True)
class ValidationIssue:
    path: str
    message: str


@dataclass(frozen=True)
class ValidationResult:
    entity_name: str
    issues: tuple[ValidationIssue, ...]

    @property
    def is_valid(self) -> bool:
        return len(self.issues) == 0


class CoreSchemaValidator:
    """Dependency-free validator for entities defined in schemas/jsonschema/core-schemas.json."""

    def __init__(self, schema_document: Mapping[str, Any]) -> None:
        definitions = schema_document.get("definitions")
        if not isinstance(definitions, Mapping):
            raise ValueError("Schema document must contain an object 'definitions' field")
        self._definitions = definitions

    @classmethod
    def from_file(cls, schema_path: Path = DEFAULT_SCHEMA_PATH) -> "CoreSchemaValidator":
        schema_document = json.loads(schema_path.read_text(encoding="utf-8"))
        return cls(schema_document)

    def validate(self, entity_name: str, payload: Any) -> ValidationResult:
        schema = self._definitions.get(entity_name)
        if not isinstance(schema, Mapping):
            raise ValueError(f"Unknown schema entity: {entity_name}")

        issues: list[ValidationIssue] = []
        self._validate_against_schema(payload, schema, "$", issues)
        return ValidationResult(entity_name=entity_name, issues=tuple(issues))

    def _validate_against_schema(
        self,
        value: Any,
        schema: Mapping[str, Any],
        path: str,
        issues: list[ValidationIssue],
    ) -> None:
        expected_type = schema.get("type")
        if expected_type is not None and not self._matches_type(value, expected_type):
            issues.append(ValidationIssue(path, f"expected type '{expected_type}'"))
            return

        if "enum" in schema and value not in schema["enum"]:
            issues.append(ValidationIssue(path, "value must match one of enum values"))

        if expected_type == "object":
            self._validate_object(value, schema, path, issues)
            return

        if expected_type == "array":
            self._validate_array(value, schema, path, issues)
            return

        if expected_type in {"integer", "number"}:
            self._validate_numeric(value, schema, path, issues)
            return

        if expected_type == "string":
            self._validate_string(value, schema, path, issues)

    def _validate_object(
        self,
        value: Mapping[str, Any],
        schema: Mapping[str, Any],
        path: str,
        issues: list[ValidationIssue],
    ) -> None:
        required = schema.get("required", [])
        for field in required:
            if field not in value:
                issues.append(ValidationIssue(path, f"missing required field '{field}'"))

        properties = schema.get("properties", {})
        for field, field_schema in properties.items():
            if field in value and isinstance(field_schema, Mapping):
                self._validate_against_schema(value[field], field_schema, f"{path}.{field}", issues)

        additional = schema.get("additionalProperties", True)
        extra_fields = [field for field in value if field not in properties]

        if additional is False:
            for field in extra_fields:
                issues.append(ValidationIssue(path, f"unexpected field '{field}'"))
            return

        if isinstance(additional, Mapping):
            for field in extra_fields:
                self._validate_against_schema(value[field], additional, f"{path}.{field}", issues)

    def _validate_array(
        self,
        value: list[Any],
        schema: Mapping[str, Any],
        path: str,
        issues: list[ValidationIssue],
    ) -> None:
        min_items = schema.get("minItems")
        if isinstance(min_items, int) and len(value) < min_items:
            issues.append(ValidationIssue(path, f"expected at least {min_items} items"))

        items_schema = schema.get("items")
        if isinstance(items_schema, Mapping):
            for index, item in enumerate(value):
                self._validate_against_schema(item, items_schema, f"{path}[{index}]", issues)

    def _validate_numeric(
        self,
        value: int | float,
        schema: Mapping[str, Any],
        path: str,
        issues: list[ValidationIssue],
    ) -> None:
        if not math.isfinite(float(value)):
            issues.append(ValidationIssue(path, "value must be finite"))
            return

        minimum = schema.get("minimum")
        if minimum is not None and value < minimum:
            issues.append(ValidationIssue(path, f"value must be >= {minimum}"))

        maximum = schema.get("maximum")
        if maximum is not None and value > maximum:
            issues.append(ValidationIssue(path, f"value must be <= {maximum}"))

    def _validate_string(
        self,
        value: str,
        schema: Mapping[str, Any],
        path: str,
        issues: list[ValidationIssue],
    ) -> None:
        expected_format = schema.get("format")
        if expected_format == "date" and not self._is_iso_date(value):
            issues.append(ValidationIssue(path, "value must be a valid ISO-8601 date (YYYY-MM-DD)"))

        if expected_format == "date-time" and not self._is_iso_datetime(value):
            issues.append(ValidationIssue(path, "value must be a valid ISO-8601 datetime"))

    @staticmethod
    def _matches_type(value: Any, expected_type: str) -> bool:
        if expected_type == "object":
            return isinstance(value, Mapping)
        if expected_type == "array":
            return isinstance(value, list)
        if expected_type == "string":
            return isinstance(value, str)
        if expected_type == "integer":
            return isinstance(value, int) and not isinstance(value, bool)
        if expected_type == "number":
            return isinstance(value, (int, float)) and not isinstance(value, bool)
        return True

    @staticmethod
    def _is_iso_date(value: str) -> bool:
        try:
            date.fromisoformat(value)
            return len(value) == 10
        except ValueError:
            return False

    @staticmethod
    def _is_iso_datetime(value: str) -> bool:
        candidate = value[:-1] + "+00:00" if value.endswith("Z") else value
        if "T" not in candidate:
            return False
        try:
            datetime.fromisoformat(candidate)
            return True
        except ValueError:
            return False


def validate_entity(entity_name: str, payload: Any, schema_path: Path = DEFAULT_SCHEMA_PATH) -> ValidationResult:
    validator = CoreSchemaValidator.from_file(schema_path=schema_path)
    return validator.validate(entity_name, payload)
