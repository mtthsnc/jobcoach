.PHONY: help lint test migrate-up migrate-down contract-test validate-openapi

PYTHON ?= python3
OPENAPI_SPEC ?= apps/api-gateway/openapi/openapi.yaml
MIGRATE_SCRIPT ?= ./scripts/migrate_sqlite_smoke.sh
MIGRATE_DB_PATH ?= .tmp/migrate-local.sqlite3
UNIT_TEST_ROOT ?= tests
UNIT_TEST_PATTERN ?= test_*.py
CONTRACT_TEST_ROOT ?= tests/contracts
JOBCOACH_API_BASE_URL ?= http://127.0.0.1:8000
JOBCOACH_API_CMD ?= $(PYTHON) apps/api-gateway/serve.py

help: ## Show available targets
	@echo "Available targets:"
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-14s %s\n", $$1, $$2}'

lint: ## Run linters (placeholder)
	@echo "lint: no linters configured yet"

test: ## Run unit tests
	@set -eu; \
	root="$(UNIT_TEST_ROOT)"; \
	pattern="$(UNIT_TEST_PATTERN)"; \
	if [ ! -d "$$root" ]; then \
	  echo "test: $$root does not exist; skipping unit tests"; \
	  exit 0; \
	fi; \
	test_files="$$(find "$$root" -type f -name "$$pattern" ! -path "$$root/contracts/*" ! -path '*/__pycache__/*' | LC_ALL=C sort)"; \
	if [ -z "$$test_files" ]; then \
	  echo "test: no unit tests found in $$root/**/$$pattern (excluding $$root/contracts)"; \
	  exit 0; \
	fi; \
	echo "test: running unit tests"; \
	printf ' - %s\n' $$test_files; \
	$(PYTHON) -m unittest -v $$test_files

migrate-up: ## Apply all SQL up migrations to a local SQLite db
	@MIGRATE_DB_PATH="$(MIGRATE_DB_PATH)" "$(MIGRATE_SCRIPT)" up

migrate-down: ## Apply SQL up+down migrations to verify rollback path
	@rm -f "$(MIGRATE_DB_PATH)"
	@MIGRATE_DB_PATH="$(MIGRATE_DB_PATH)" "$(MIGRATE_SCRIPT)" down

contract-test: ## Run deterministic migration rollback + contract artifact validation
	@rm -f "$(MIGRATE_DB_PATH)"
	@MIGRATE_DB_PATH="$(MIGRATE_DB_PATH)" "$(MIGRATE_SCRIPT)" down
	@JOBCOACH_API_BASE_URL="$(JOBCOACH_API_BASE_URL)" JOBCOACH_API_CMD="$(JOBCOACH_API_CMD)" $(PYTHON) -m unittest discover -s "$(CONTRACT_TEST_ROOT)" -p "$(UNIT_TEST_PATTERN)" -v

validate-openapi: ## Validate runtime OpenAPI contract
	@./scripts/validate_openapi.sh $(OPENAPI_SPEC)
