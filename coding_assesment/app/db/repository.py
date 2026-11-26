"""Postgres adapter for the query port: runs LLM-derived SQL as the read-only role."""

import math
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Engine
from sqlalchemy.exc import DBAPIError, InterfaceError, OperationalError

from app.db.connection import create_engine_from_env
from app.db.ports import (
    DatabaseUnavailableError,
    QueryExecutionError,
    QueryFailedError,
    QueryResult,
    QueryTimeoutError,
)
from app.schemas import Cell

MAX_ROWS = 1000
STATEMENT_TIMEOUT = "5s"
_QUERY_CANCELED = "57014"
# SQLSTATE classes that are server-side outages, not faults of the statement:
# 08 connection exception, 53 insufficient resources, 57 operator intervention.
_OUTAGE_CLASSES = ("08", "53", "57")
# The allowlisted objects are missing or unreadable: a deployment problem.
_SETUP_SQLSTATES = ("42P01", "42501")


def to_cell(value: object) -> Cell:
    """Make a driver value representable as a ``Cell``.

    Anything the response schema cannot carry (arrays, intervals, bytes) or that
    JSON would silently turn into null (NaN, Infinity) becomes text.
    """
    if value is None or isinstance(value, str | bool | int | date | datetime):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else str(Decimal(value))
    if isinstance(value, Decimal):
        return value if value.is_finite() else str(value)
    if isinstance(value, bytes):
        return "\\x" + value.hex()
    return str(value)


class PostgresQueryRepository:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def run_select(self, sql: str) -> QueryResult:
        try:
            with self._engine.connect() as conn, conn.begin():
                # Explicit, so safety does not rest on the role defaults alone.
                conn.exec_driver_sql("SET TRANSACTION READ ONLY")
                conn.exec_driver_sql(
                    f"SET LOCAL statement_timeout = '{STATEMENT_TIMEOUT}'"
                )
                # exec_driver_sql, not text(): ":word" in the SQL must not become a bind.
                # psycopg still reads "%" as a placeholder start, so escape it.
                result = conn.exec_driver_sql(sql.replace("%", "%%"))
                fetched = result.fetchmany(MAX_ROWS + 1)
                columns = list(result.keys())
        except DBAPIError as exc:
            raise _map_error(exc) from exc
        return QueryResult(
            columns=columns,
            rows=[[to_cell(v) for v in row] for row in fetched[:MAX_ROWS]],
            truncated=len(fetched) > MAX_ROWS,
        )


def _map_error(exc: DBAPIError) -> QueryExecutionError:
    sqlstate = getattr(exc.orig, "sqlstate", None)
    if sqlstate == _QUERY_CANCELED:
        return QueryTimeoutError("the query exceeded the time limit")
    if sqlstate is None and isinstance(exc, OperationalError | InterfaceError):
        return DatabaseUnavailableError("the database is unavailable")
    if sqlstate and sqlstate.startswith(_OUTAGE_CLASSES):
        return DatabaseUnavailableError("the database is unavailable")
    if sqlstate in _SETUP_SQLSTATES:
        return QueryExecutionError(
            f"the database is not set up for this query (SQLSTATE {sqlstate})"
        )
    detail = f" (SQLSTATE {sqlstate})" if sqlstate else ""
    return QueryFailedError(f"the database rejected the query{detail}")


def create_query_repository_from_env() -> PostgresQueryRepository:
    """Build the repository on the ``app_ro`` engine (``READONLY_DATABASE_URL``)."""
    return PostgresQueryRepository(create_engine_from_env("READONLY_DATABASE_URL"))
