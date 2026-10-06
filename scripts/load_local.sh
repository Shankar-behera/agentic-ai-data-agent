#!/usr/bin/env bash
# Create + seed rides_db on a local Postgres (no Docker). Usage: scripts/load_local.sh [host] [port] [user]
set -euo pipefail
HOST="${1:-localhost}"; PORT="${2:-5432}"; USER_="${3:-postgres}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export PGPASSWORD="${PGPASSWORD:-postgres}"
psql -h "$HOST" -p "$PORT" -U "$USER_" -v ON_ERROR_STOP=1 -d postgres -c "DROP DATABASE IF EXISTS rides_db" -c "CREATE DATABASE rides_db"
psql -h "$HOST" -p "$PORT" -U "$USER_" -v ON_ERROR_STOP=1 -d rides_db -f "$ROOT/db/init/01_schema.sql"
cd "$ROOT/data/seed"   # \copy paths are relative to psql's working directory
for t in users vehicles rides ratings payments; do
  psql -h "$HOST" -p "$PORT" -U "$USER_" -v ON_ERROR_STOP=1 -d rides_db \
    -c "\\copy $t FROM '$t.csv' WITH (FORMAT csv, HEADER true, NULL '')"
done
echo "Loaded rides_db. Create the read-only role with db/init/03_readonly_role.sh (see README)."
