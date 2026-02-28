# Monorepo Phase A Freeze (MONO-A)

Captured at: `2026-02-28T17:55:30Z` (UTC)
Scope: freeze current contract artifacts, migration assets, and path references before any relocation wave.

## A. Destination Directories Created

- `packages/`
- `schemas/openapi/`
- `schemas/jsonschema/`
- `tools/scripts/`

No runtime files were moved or refactored in Phase A.

## B. Frozen Artifact Checksums

| Path | SHA-256 |
|---|---|
| `docs/artifacts/openapi-m0-m2.yaml` | `75a4fb86b881ff312b59dfde5a1f7bb18aa4ec62f8aa357480c9fddff0d0ef57` |
| `docs/artifacts/core-schemas.json` | `82f8416857d950b31c5e06c07e2fb997dbe46c505ffd46afb5acf51445be8df6` |
| `infra/migrations/001_m0_ingestion_foundations.sql` | `178ef9700dfd2061ab5d3e640ac99cd6dc49b7f9df28953abc416f4915be56cd` |
| `infra/migrations/002_m0_job_specs.sql` | `831b8c31a4cf4f5c4b82c76bbeeb27ba251b1fd1fd30b4f219c2a1cd1a5ea614` |
| `infra/migrations/003_m0_candidate_profiles.sql` | `313816d45c4d8ff1f652d365c9bb8c44b3043518118f71f7e1c8cdc74364c34d` |
| `infra/migrations/004_m0_taxonomy_eval_outbox.sql` | `7ee1b9b0b05e555ef15d6f9d5bbfc38835432bc275bd19137ee4accec06ee373` |

Runtime OpenAPI symlink at freeze time:
- `apps/api-gateway/openapi/openapi.yaml -> ../../../docs/artifacts/openapi-m0-m2.yaml`

## C. Frozen Reference Points (for Phase B/C edits)

| Reference | Why frozen now |
|---|---|
| `Makefile:4` | Runtime OpenAPI path default (`OPENAPI_SPEC`). |
| `Makefile:5` | Migration runner script path default (`MIGRATE_SCRIPT`). |
| `Makefile:50` | OpenAPI validation command references `scripts/validate_openapi.sh`. |
| `scripts/validate_openapi.sh:11-12` | Hardcoded runtime/artifact OpenAPI path wiring. |
| `scripts/migrate_sqlite_smoke.sh:19,41` | Migration directory default and env contract. |
| `services/quality-eval/schema_validation/validator.py:11` | JSON schema default source path (`docs/artifacts/core-schemas.json`). |
| `tests/contracts/README.md:34` | Docs mention migration source path pattern (`infra/migrations/*.sql`). |

## D. Path Mapping Table (Old -> Planned New)

| Old path | Planned new path | Planned phase | Compatibility note |
|---|---|---|---|
| `docs/artifacts/openapi-m0-m2.yaml` | `schemas/openapi/openapi-m0-m2.yaml` | Phase B | Keep legacy path via symlink/stub until Phase D cleanup. |
| `apps/api-gateway/openapi/openapi.yaml` | `schemas/openapi/openapi.yaml` | Phase B | Keep API gateway compatibility path until imports/scripts are updated. |
| `docs/artifacts/core-schemas.json` | `schemas/jsonschema/core-schemas.json` | Phase B | Keep legacy docs path via symlink/stub during transition. |
| `scripts/validate_openapi.sh` | `tools/scripts/validate_openapi.sh` | Phase B | Keep legacy `scripts/` entrypoint as shim during transition. |
| `scripts/migrate_sqlite_smoke.sh` | `tools/scripts/migrate_sqlite_smoke.sh` | Phase B | Keep legacy `scripts/` entrypoint as shim during transition. |
| `infra/migrations/*.sql` | `infra/migrations/*.sql` (unchanged) | Phase B/C | No move planned in current target shape; references still tracked. |

## E. Phase A Exit Check

- Destination directories exist.
- Mapping table documented.
- Freeze snapshot recorded before any move wave.
- Behavior intentionally unchanged in this phase.
