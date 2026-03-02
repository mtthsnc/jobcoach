.PHONY: help lint test benchmark-extraction benchmark-candidate-parse benchmark-interview-relevance benchmark-feedback-quality benchmark-trajectory-quality benchmark-negotiation-quality benchmark-eval-orchestration migrate-up migrate-down contract-test validate-openapi docker-build docker-up docker-url docker-down docker-logs docker-ps docker-shell docker-test

PYTHON ?= python3
OPENAPI_SPEC ?= schemas/openapi/openapi.yaml
MIGRATE_SCRIPT ?= ./tools/scripts/migrate_sqlite_smoke.sh
MIGRATE_DB_PATH ?= .tmp/migrate-local.sqlite3
UNIT_TEST_ROOT ?= tests
UNIT_TEST_PATTERN ?= test_*.py
CONTRACT_TEST_ROOT ?= tests/contracts
JOBCOACH_API_BASE_URL ?= http://127.0.0.1:8000
JOBCOACH_API_CMD ?= $(PYTHON) apps/api-gateway/serve.py
BENCHMARK_RUNNER ?= services/quality-eval/benchmark/extraction_benchmark.py
BENCHMARK_FIXTURE_DIR ?= tests/unit/fixtures/job_extraction
BENCHMARK_REPORT_PATH ?= .tmp/extraction-benchmark-report.json
CANDIDATE_BENCHMARK_RUNNER ?= services/quality-eval/benchmark/candidate_parse_benchmark.py
CANDIDATE_BENCHMARK_FIXTURE_DIR ?= tests/unit/fixtures/candidate_parsing
CANDIDATE_BENCHMARK_REPORT_PATH ?= .tmp/candidate-parse-benchmark-report.json
INTERVIEW_BENCHMARK_RUNNER ?= services/quality-eval/benchmark/interview_relevance_benchmark.py
INTERVIEW_BENCHMARK_FIXTURE_DIR ?= tests/unit/fixtures/interview_relevance
INTERVIEW_BENCHMARK_REPORT_PATH ?= .tmp/interview-relevance-benchmark-report.json
FEEDBACK_BENCHMARK_RUNNER ?= services/quality-eval/benchmark/feedback_quality_benchmark.py
FEEDBACK_BENCHMARK_FIXTURE_DIR ?= tests/unit/fixtures/feedback_quality
FEEDBACK_BENCHMARK_REPORT_PATH ?= .tmp/feedback-quality-benchmark-report.json
DOCKER_COMPOSE ?= docker compose
DOCKER_SERVICE ?= api
DOCKER_IMAGE ?= jobcoach-api:dev
DOCKER_HOST_PORT ?= 0
TRAJECTORY_BENCHMARK_RUNNER ?= services/quality-eval/benchmark/trajectory_quality_benchmark.py
TRAJECTORY_BENCHMARK_FIXTURE_DIR ?= tests/unit/fixtures/trajectory_quality
TRAJECTORY_BENCHMARK_REPORT_PATH ?= .tmp/trajectory-quality-benchmark-report.json
NEGOTIATION_BENCHMARK_RUNNER ?= services/quality-eval/benchmark/negotiation_quality_benchmark.py
NEGOTIATION_BENCHMARK_FIXTURE_DIR ?= tests/unit/fixtures/negotiation_quality
NEGOTIATION_BENCHMARK_REPORT_PATH ?= .tmp/negotiation-quality-benchmark-report.json
EVAL_ORCHESTRATION_BENCHMARK_RUNNER ?= services/quality-eval/benchmark/eval_orchestration_benchmark.py
EVAL_ORCHESTRATION_BENCHMARK_FIXTURE_DIR ?= tests/unit/fixtures/eval_orchestration
EVAL_ORCHESTRATION_BENCHMARK_REPORT_PATH ?= .tmp/eval-orchestration-benchmark-report.json

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
	$(PYTHON) -m unittest -v $$test_files; \
	echo "test: running extraction benchmark threshold gate"; \
	$(PYTHON) "$(BENCHMARK_RUNNER)" --fixtures-dir "$(BENCHMARK_FIXTURE_DIR)" --report-path "$(BENCHMARK_REPORT_PATH)"; \
	echo "test: running candidate parse benchmark threshold gate"; \
	$(PYTHON) "$(CANDIDATE_BENCHMARK_RUNNER)" --fixtures-dir "$(CANDIDATE_BENCHMARK_FIXTURE_DIR)" --report-path "$(CANDIDATE_BENCHMARK_REPORT_PATH)"; \
	echo "test: running interview relevance benchmark threshold gate"; \
	$(PYTHON) "$(INTERVIEW_BENCHMARK_RUNNER)" --fixtures-dir "$(INTERVIEW_BENCHMARK_FIXTURE_DIR)" --report-path "$(INTERVIEW_BENCHMARK_REPORT_PATH)"; \
	echo "test: running feedback quality benchmark threshold gate"; \
	$(PYTHON) "$(FEEDBACK_BENCHMARK_RUNNER)" --fixtures-dir "$(FEEDBACK_BENCHMARK_FIXTURE_DIR)" --report-path "$(FEEDBACK_BENCHMARK_REPORT_PATH)"; \
	echo "test: running trajectory quality benchmark threshold gate"; \
	$(PYTHON) "$(TRAJECTORY_BENCHMARK_RUNNER)" --fixtures-dir "$(TRAJECTORY_BENCHMARK_FIXTURE_DIR)" --report-path "$(TRAJECTORY_BENCHMARK_REPORT_PATH)"; \
	echo "test: running negotiation quality benchmark threshold gate"; \
	$(PYTHON) "$(NEGOTIATION_BENCHMARK_RUNNER)" --fixtures-dir "$(NEGOTIATION_BENCHMARK_FIXTURE_DIR)" --report-path "$(NEGOTIATION_BENCHMARK_REPORT_PATH)"; \
	echo "test: running eval orchestration benchmark threshold gate"; \
	$(PYTHON) "$(EVAL_ORCHESTRATION_BENCHMARK_RUNNER)" --fixtures-dir "$(EVAL_ORCHESTRATION_BENCHMARK_FIXTURE_DIR)" --report-path "$(EVAL_ORCHESTRATION_BENCHMARK_REPORT_PATH)"

benchmark-extraction: ## Run extraction benchmark threshold gate and emit report
	@$(PYTHON) "$(BENCHMARK_RUNNER)" --fixtures-dir "$(BENCHMARK_FIXTURE_DIR)" --report-path "$(BENCHMARK_REPORT_PATH)"

benchmark-candidate-parse: ## Run candidate parse benchmark threshold gate and emit report
	@$(PYTHON) "$(CANDIDATE_BENCHMARK_RUNNER)" --fixtures-dir "$(CANDIDATE_BENCHMARK_FIXTURE_DIR)" --report-path "$(CANDIDATE_BENCHMARK_REPORT_PATH)"

benchmark-interview-relevance: ## Run interview relevance benchmark threshold gate and emit report
	@$(PYTHON) "$(INTERVIEW_BENCHMARK_RUNNER)" --fixtures-dir "$(INTERVIEW_BENCHMARK_FIXTURE_DIR)" --report-path "$(INTERVIEW_BENCHMARK_REPORT_PATH)"

benchmark-feedback-quality: ## Run feedback quality benchmark threshold gate and emit report
	@$(PYTHON) "$(FEEDBACK_BENCHMARK_RUNNER)" --fixtures-dir "$(FEEDBACK_BENCHMARK_FIXTURE_DIR)" --report-path "$(FEEDBACK_BENCHMARK_REPORT_PATH)"

benchmark-trajectory-quality: ## Run trajectory quality benchmark threshold gate and emit report
	@$(PYTHON) "$(TRAJECTORY_BENCHMARK_RUNNER)" --fixtures-dir "$(TRAJECTORY_BENCHMARK_FIXTURE_DIR)" --report-path "$(TRAJECTORY_BENCHMARK_REPORT_PATH)"

benchmark-negotiation-quality: ## Run negotiation/follow-up quality benchmark threshold gate and emit report
	@$(PYTHON) "$(NEGOTIATION_BENCHMARK_RUNNER)" --fixtures-dir "$(NEGOTIATION_BENCHMARK_FIXTURE_DIR)" --report-path "$(NEGOTIATION_BENCHMARK_REPORT_PATH)"

benchmark-eval-orchestration: ## Run eval orchestration quality benchmark threshold gate and emit report
	@$(PYTHON) "$(EVAL_ORCHESTRATION_BENCHMARK_RUNNER)" --fixtures-dir "$(EVAL_ORCHESTRATION_BENCHMARK_FIXTURE_DIR)" --report-path "$(EVAL_ORCHESTRATION_BENCHMARK_REPORT_PATH)"

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
	@./tools/scripts/validate_openapi.sh $(OPENAPI_SPEC)

docker-build: ## Build Docker image for API runtime
	@docker build -t "$(DOCKER_IMAGE)" .

docker-up: ## Start API via docker compose
	@DOCKER_HOST_PORT="$(DOCKER_HOST_PORT)" $(DOCKER_COMPOSE) up --build -d "$(DOCKER_SERVICE)"
	@$(MAKE) docker-url DOCKER_HOST_PORT="$(DOCKER_HOST_PORT)"

docker-url: ## Print API URL for current docker compose port mapping
	@set -eu; \
	mapped="$$(DOCKER_HOST_PORT="$(DOCKER_HOST_PORT)" $(DOCKER_COMPOSE) port "$(DOCKER_SERVICE)" 8000 2>/dev/null | head -n1 || true)"; \
	if [ -z "$$mapped" ]; then \
	  echo "docker-url: no published port found (is $(DOCKER_SERVICE) running?)"; \
	  exit 1; \
	fi; \
	host_port="$$(printf '%s\n' "$$mapped" | sed -E 's/.*:([0-9]+)$$/\1/')"; \
	echo "API URL: http://127.0.0.1:$$host_port"

docker-down: ## Stop docker compose services
	@$(DOCKER_COMPOSE) down

docker-logs: ## Tail API logs from docker compose
	@$(DOCKER_COMPOSE) logs -f "$(DOCKER_SERVICE)"

docker-ps: ## Show docker compose service status
	@$(DOCKER_COMPOSE) ps

docker-shell: ## Open an interactive shell in the API container
	@$(DOCKER_COMPOSE) run --rm "$(DOCKER_SERVICE)" bash

docker-test: ## Run test + contract gates inside container
	@$(DOCKER_COMPOSE) build "$(DOCKER_SERVICE)"
	@$(DOCKER_COMPOSE) run --rm -e JOBCOACH_AUTO_MIGRATE=0 -e MIGRATE_DB_PATH=/tmp/migrate-local.sqlite3 "$(DOCKER_SERVICE)" make test validate-openapi contract-test
