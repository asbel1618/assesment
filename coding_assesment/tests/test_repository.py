"""Repository mapping and cell normalization. Hermetic: no database."""

import pytest
from sqlalchemy.exc import DBAPIError, OperationalError

from app.db.repository import (
    DatabaseUnavailableError,
    QueryExecutionError,
    QueryFailedError,
    QueryTimeoutError,
    _map_error,
)


class FakeDriverError(Exception):
    def __init__(self, sqlstate: str | None) -> None:
        super().__init__("driver error")
        self.sqlstate = sqlstate


def _dbapi_error(
    sqlstate: str | None, cls: type[DBAPIError] = DBAPIError
) -> DBAPIError:
    return cls("SELECT 1", {}, FakeDriverError(sqlstate))


@pytest.mark.parametrize("sqlstate", ["42703", "22012", "42883", "22P02"])
def test_statement_errors_are_query_failed(sqlstate: str) -> None:
    error = _map_error(_dbapi_error(sqlstate))

    assert type(error) is QueryFailedError
    assert sqlstate in error.reason


def test_statement_timeout_is_a_timeout() -> None:
    assert isinstance(_map_error(_dbapi_error("57014")), QueryTimeoutError)


@pytest.mark.parametrize("sqlstate", ["57P01", "57P03", "53200", "53300", "08006"])
def test_server_side_outages_are_database_unavailable(sqlstate: str) -> None:
    assert isinstance(_map_error(_dbapi_error(sqlstate)), DatabaseUnavailableError)


def test_connection_failure_without_sqlstate_is_database_unavailable() -> None:
    error = _map_error(_dbapi_error(None, OperationalError))

    assert isinstance(error, DatabaseUnavailableError)


@pytest.mark.parametrize("sqlstate", ["42P01", "42501"])
def test_missing_objects_and_privileges_are_not_blamed_on_the_sql(
    sqlstate: str,
) -> None:
    error = _map_error(_dbapi_error(sqlstate))

    assert type(error) is QueryExecutionError
    assert sqlstate in error.reason
