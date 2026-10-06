#!/bin/sh
# Loads the CSVs from /seed (mounted read-only by docker-compose). Runs once, on first DB init.
set -eu
SEED_DIR="${SEED_DIR:-/seed}"
for t in users vehicles rides ratings payments; do
  if [ -f "$SEED_DIR/$t.csv" ]; then
    echo "seeding $t"
    psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
      -c "\\copy $t FROM '$SEED_DIR/$t.csv' WITH (FORMAT csv, HEADER true, NULL '')"
  else
    echo "no seed file for $t, skipping"
  fi
done
