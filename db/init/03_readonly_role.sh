#!/bin/sh
# Creates the SELECT-only role the agent uses to run LLM-generated SQL.
set -eu
: "${DB_READONLY_USER:?DB_READONLY_USER must be set}"
: "${DB_READONLY_PASSWORD:?DB_READONLY_PASSWORD must be set}"
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
  -v ro_user="$DB_READONLY_USER" -v ro_pass="$DB_READONLY_PASSWORD" -v dbname="$POSTGRES_DB" <<'SQL'
SELECT format('CREATE ROLE %I LOGIN PASSWORD %L NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT', :'ro_user', :'ro_pass')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'ro_user') \gexec
SELECT format('ALTER ROLE %I SET default_transaction_read_only = on', :'ro_user') \gexec
SELECT format('ALTER ROLE %I SET statement_timeout = ''15s''', :'ro_user') \gexec
SELECT format('REVOKE ALL ON DATABASE %I FROM PUBLIC', :'dbname') \gexec
SELECT format('GRANT CONNECT ON DATABASE %I TO %I', :'dbname', :'ro_user') \gexec
SELECT format('GRANT USAGE ON SCHEMA public TO %I', :'ro_user') \gexec
SELECT format('GRANT SELECT ON ALL TABLES IN SCHEMA public TO %I', :'ro_user') \gexec
SELECT format('ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO %I', :'ro_user') \gexec
SQL
