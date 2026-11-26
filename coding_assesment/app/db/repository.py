"""Query execution as the read-only role. The only module that runs LLM-derived SQL."""

import math
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Protocol

from sqlalchemy import Engine
from sqlalchemy.exc import DBAPIError, InterfaceError, OperationalError

from app.db.connection import create_engine_from_env
from app.schemas import Cell

MAX_ROWS = 1000
STATEMENT_TIMEOUT = "5s"
_QUERY_CANCELED = "57014"
# SQLSTATE classes that are server-side outages, not faults of the statement:
# 08 connection exception, 53 insufficient resources, 57 operator intervention.
_OUTAGE_CLASSES = ("08", "53", "57")
# The allowlisted objects are missing or unreadable: a deployment problem.
_SETUP_SQLSTATES = ("42P01", "42501")


class QueryExecutionError(Exception):
    """Base for execution failures; ``reason`` is safe to show to API callers."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class QueryFailedError(QueryExecutionError):
    """PostgreSQL rejected the statement (unknown column, bad cast, ...)."""


class QueryTimeoutError(QueryExecutionError):
    """The statement exceeded the statement timeout."""


class DatabaseUnavailableError(QueryExecutionError):
    """The database could not be reached."""


@dataclass(frozen=True)
class QueryResult:
    columns: list[str]
    rows: list[list[Cell]]
    truncated: bool


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


class QueryRepository(Protocol):
    def run_select(self, sql: str) -> QueryResult:
        """Execute validated ``sql``; raises ``QueryExecutionError``."""
        ...


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
