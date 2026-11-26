#!/bin/sh
# Creates the read-only role `app_ro` used by the API.
# Runs once, on first init of an empty data volume (docker-entrypoint-initdb.d).
set -eu

: "${APP_RO_PASSWORD:?APP_RO_PASSWORD must be set}"

psql -v ON_ERROR_STOP=1 \
  -v ro_password="$APP_RO_PASSWORD" \
  -v owner="$POSTGRES_USER" \
  -v db="$POSTGRES_DB" \
  --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<'SQL'
CREATE ROLE app_ro LOGIN PASSWORD :'ro_password';

-- Session defaults: read-only transactions and a bounded statement time.
ALTER ROLE app_ro SET default_transaction_read_only = on;
ALTER ROLE app_ro SET statement_timeout = '5s';

-- Drops the implicit PUBLIC grants (incl. TEMP, which would allow temp tables).
REVOKE ALL ON DATABASE :"db" FROM PUBLIC;
GRANT CONNECT ON DATABASE :"db" TO app_ro;

REVOKE CREATE ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO app_ro;

-- Tables/views later created by the owner (orders, step-4 views) are SELECT-only for app_ro.
ALTER DEFAULT PRIVILEGES FOR ROLE :"owner" IN SCHEMA public
  GRANT SELECT ON TABLES TO app_ro;
SQL
