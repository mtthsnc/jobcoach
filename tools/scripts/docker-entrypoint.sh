#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="${REPO_ROOT:-/app}"
HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-8000}"
JOBCOACH_DB_PATH="${JOBCOACH_DB_PATH:-/data/jobcoach.sqlite3}"
MIGRATE_DB_PATH="${MIGRATE_DB_PATH:-${JOBCOACH_DB_PATH}}"
JOBCOACH_AUTO_MIGRATE="${JOBCOACH_AUTO_MIGRATE:-1}"

export HOST
export PORT
export JOBCOACH_DB_PATH
export MIGRATE_DB_PATH
export JOBCOACH_AUTO_MIGRATE

mkdir -p "${REPO_ROOT}/.tmp" "$(dirname "${JOBCOACH_DB_PATH}")"
cd "${REPO_ROOT}"

if [[ "${JOBCOACH_AUTO_MIGRATE}" == "1" ]]; then
  echo "[entrypoint] applying migrations to ${MIGRATE_DB_PATH}"
  "${REPO_ROOT}/tools/scripts/migrate_sqlite_smoke.sh" up
else
  echo "[entrypoint] skipping migrations (JOBCOACH_AUTO_MIGRATE=${JOBCOACH_AUTO_MIGRATE})"
fi

if [[ "$#" -eq 0 ]]; then
  set -- python3 apps/api-gateway/serve.py
fi

echo "[entrypoint] starting: $*"
exec "$@"
