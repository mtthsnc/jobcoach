#!/usr/bin/env bash
set -euo pipefail

fail() {
  echo "ERROR: $*" >&2
  exit 1
}

usage() {
  cat <<'USAGE'
Usage: tools/scripts/migrate_sqlite_smoke.sh [up|down|smoke]

Modes:
  up     Apply all goose-style Up sections in order.
  down   Apply all Up sections, then all Down sections in reverse order.
  smoke  Same as down, but runs against a temporary db and removes it.

Environment:
  MIGRATIONS_DIR   Path to migration SQL files (default: infra/migrations)
  MIGRATE_DB_PATH  SQLite db path for up/down modes (default: .tmp/migrate-local.sqlite3)
  MIGRATE_KEEP_DB  Set to 1 to keep temporary smoke db for debugging
USAGE
}

MODE="${1:-smoke}"
if [[ "${MODE}" == "-h" || "${MODE}" == "--help" ]]; then
  usage
  exit 0
fi

case "${MODE}" in
  up|down|smoke) ;;
  *)
    usage
    fail "invalid mode: ${MODE}"
    ;;
esac

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
MIGRATIONS_DIR="${MIGRATIONS_DIR:-${REPO_ROOT}/infra/migrations}"
DEFAULT_DB_PATH="${REPO_ROOT}/.tmp/migrate-local.sqlite3"
DB_PATH="${MIGRATE_DB_PATH:-${DEFAULT_DB_PATH}}"

[[ -d "${MIGRATIONS_DIR}" ]] || fail "migrations directory not found: ${MIGRATIONS_DIR}"
command -v python3 >/dev/null 2>&1 || fail "python3 is required"

cleanup_smoke_db=0
if [[ "${MODE}" == "smoke" ]]; then
  DB_PATH="$(mktemp "${TMPDIR:-/tmp}/jobcoach-migrate-smoke-XXXXXX.sqlite3")"
  cleanup_smoke_db=1
else
  mkdir -p "$(dirname "${DB_PATH}")"
  rm -f "${DB_PATH}"
fi

echo "[migrate-sqlite] mode=${MODE}"
echo "[migrate-sqlite] db=${DB_PATH}"
echo "[migrate-sqlite] migrations=${MIGRATIONS_DIR}"

python3 - "${MODE}" "${DB_PATH}" "${MIGRATIONS_DIR}" <<'PY'
from __future__ import annotations

import re
import sqlite3
import sys
from pathlib import Path

MODE = sys.argv[1]
DB_PATH = Path(sys.argv[2])
MIGRATIONS_DIR = Path(sys.argv[3])

UP_MARKER = re.compile(r"^\s*--\s*\+goose\s+Up\s*$")
DOWN_MARKER = re.compile(r"^\s*--\s*\+goose\s+Down\s*$")


def parse_migration(path: Path) -> tuple[str, str]:
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)

    up_idx = None
    down_idx = None
    for idx, line in enumerate(lines):
        if up_idx is None and UP_MARKER.match(line):
            up_idx = idx
            continue
        if up_idx is not None and DOWN_MARKER.match(line):
            down_idx = idx
            break

    if up_idx is None:
        raise RuntimeError(f"{path.name}: missing '-- +goose Up' marker")
    if down_idx is None:
        raise RuntimeError(f"{path.name}: missing '-- +goose Down' marker")
    if down_idx <= up_idx:
        raise RuntimeError(f"{path.name}: invalid marker order")

    up_sql = "".join(lines[up_idx + 1 : down_idx]).strip()
    down_sql = "".join(lines[down_idx + 1 :]).strip()

    if not up_sql:
        raise RuntimeError(f"{path.name}: Up section is empty")
    if not down_sql:
        raise RuntimeError(f"{path.name}: Down section is empty")

    return up_sql + "\n", down_sql + "\n"


def load_migrations(migrations_dir: Path) -> list[tuple[str, str, str]]:
    files = sorted(migrations_dir.glob("*.sql"))
    if not files:
        raise RuntimeError(f"no .sql migrations found in {migrations_dir}")

    parsed: list[tuple[str, str, str]] = []
    for path in files:
        up_sql, down_sql = parse_migration(path)
        parsed.append((path.name, up_sql, down_sql))
    return parsed


def user_tables(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        """
        SELECT name
        FROM sqlite_master
        WHERE type = 'table' AND name NOT LIKE 'sqlite_%'
        ORDER BY name
        """
    ).fetchall()
    return [row[0] for row in rows]


migrations = load_migrations(MIGRATIONS_DIR)

conn = sqlite3.connect(DB_PATH)
try:
    conn.execute("PRAGMA foreign_keys = ON")

    for name, up_sql, _ in migrations:
        print(f"[migrate-sqlite] up   {name}")
        conn.executescript(up_sql)

    if MODE in {"down", "smoke"}:
        for name, _, down_sql in reversed(migrations):
            print(f"[migrate-sqlite] down {name}")
            conn.executescript(down_sql)

    tables = user_tables(conn)
    if MODE == "up":
        if not tables:
            raise RuntimeError("up migration completed but no user tables exist")
        print(f"[migrate-sqlite] user tables after up ({len(tables)}): {', '.join(tables)}")
    else:
        if tables:
            raise RuntimeError(
                f"expected no user tables after {MODE}, found: {', '.join(tables)}"
            )
        print(f"[migrate-sqlite] user tables after {MODE}: none")

    conn.commit()
except Exception as exc:  # pragma: no cover - shell script reports details
    conn.rollback()
    raise RuntimeError(str(exc)) from exc
finally:
    conn.close()
PY

if [[ ${cleanup_smoke_db} -eq 1 && "${MIGRATE_KEEP_DB:-0}" != "1" ]]; then
  rm -f "${DB_PATH}"
  echo "[migrate-sqlite] removed smoke db"
fi
