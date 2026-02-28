from __future__ import annotations

import json
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
OPENAPI_PATH = ROOT / "docs" / "artifacts" / "openapi-m0-m2.yaml"
SCHEMAS_PATH = ROOT / "docs" / "artifacts" / "core-schemas.json"
HTTP_METHODS = {"get", "post", "put", "patch", "delete", "head", "options", "trace"}


def _load_openapi_text() -> str:
    return OPENAPI_PATH.read_text(encoding="utf-8")


def _load_core_schemas() -> dict:
    return json.loads(SCHEMAS_PATH.read_text(encoding="utf-8"))


def _extract_paths_and_methods(openapi_text: str) -> dict[str, list[str]]:
    in_paths = False
    current_path: str | None = None
    path_methods: dict[str, list[str]] = {}

    for line in openapi_text.splitlines():
        if line.strip() == "paths:":
            in_paths = True
            continue
        if in_paths and line.strip() == "components:":
            break
        if not in_paths:
            continue

        path_match = re.match(r"^  (/[^:]+):\s*$", line)
        if path_match:
            current_path = path_match.group(1)
            path_methods[current_path] = []
            continue

        method_match = re.match(r"^    ([a-z]+):\s*$", line)
        if method_match and current_path:
            method = method_match.group(1)
            if method in HTTP_METHODS:
                path_methods[current_path].append(method)

    return path_methods


def _extract_operation_ids(openapi_text: str) -> list[str]:
    return re.findall(r"^\s{6}operationId:\s*([A-Za-z0-9_]+)\s*$", openapi_text, flags=re.MULTILINE)


class ContractArtifactScaffoldTest(unittest.TestCase):
    def test_artifact_files_exist(self) -> None:
        self.assertTrue(OPENAPI_PATH.is_file(), f"Missing OpenAPI artifact: {OPENAPI_PATH}")
        self.assertTrue(SCHEMAS_PATH.is_file(), f"Missing core schema artifact: {SCHEMAS_PATH}")

    def test_core_schemas_json_is_parseable(self) -> None:
        data = _load_core_schemas()
        self.assertIsInstance(data, dict)
        self.assertEqual(data.get("type"), "object")
        self.assertIn("definitions", data)
        self.assertIsInstance(data["definitions"], dict)
        self.assertGreater(len(data["definitions"]), 0)

    def test_core_schema_definitions_have_required_shape(self) -> None:
        definitions = _load_core_schemas()["definitions"]
        for name, schema in definitions.items():
            self.assertIsInstance(schema, dict, f"{name}: definition must be an object")
            self.assertEqual(schema.get("type"), "object", f"{name}: expected type=object")
            self.assertIn("properties", schema, f"{name}: missing properties")
            self.assertIsInstance(schema["properties"], dict, f"{name}: properties must be an object")

    def test_openapi_document_has_basics(self) -> None:
        text = _load_openapi_text()
        self.assertIn("openapi: 3.1.0", text)
        self.assertIn("\npaths:\n", text)
        self.assertIn("\ncomponents:\n", text)

    def test_openapi_paths_define_http_methods(self) -> None:
        path_methods = _extract_paths_and_methods(_load_openapi_text())
        self.assertGreater(len(path_methods), 0, "No API paths found under 'paths'")
        for path, methods in path_methods.items():
            self.assertGreater(len(methods), 0, f"{path}: no HTTP methods detected")

    def test_openapi_operation_ids_are_unique(self) -> None:
        operation_ids = _extract_operation_ids(_load_openapi_text())
        self.assertGreater(len(operation_ids), 0, "No operationId entries found")
        self.assertEqual(len(operation_ids), len(set(operation_ids)), "operationId values must be unique")


if __name__ == "__main__":
    unittest.main(verbosity=2)
