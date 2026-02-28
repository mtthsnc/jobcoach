from __future__ import annotations

from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]
OPENAPI_ARTIFACT_PATH = ROOT_DIR / "schemas" / "openapi" / "openapi-m0-m2.yaml"
OPENAPI_RUNTIME_PATH = ROOT_DIR / "schemas" / "openapi" / "openapi.yaml"
CORE_SCHEMAS_PATH = ROOT_DIR / "schemas" / "jsonschema" / "core-schemas.json"
