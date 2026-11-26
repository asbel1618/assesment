"""Repository mapping and cell normalization. Hermetic: no database."""

from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy.exc import DBAPIError, OperationalError

from app.db.ports import (
    DatabaseUnavailableError,
    QueryExecutionError,
    QueryFailedError,
    QueryTimeoutError,
)
from app.db.repository import _map_error, to_cell


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


@pytest.mark.parametrize(
    "value",
    [
        None,
        True,
        7,
        1.5,
        "text",
        Decimal("8084.52"),
        date(2025, 3, 31),
        datetime(2025, 3, 31, 12, 0),
    ],
)
def test_supported_cells_pass_through_unchanged(value: object) -> None:
    assert to_cell(value) is value


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (float("nan"), "NaN"),
        (float("inf"), "Infinity"),
        (float("-inf"), "-Infinity"),
        (Decimal("NaN"), "NaN"),
        (Decimal("Infinity"), "Infinity"),
        (timedelta(days=3), "3 days, 0:00:00"),
        (["a", "b"], "['a', 'b']"),
        (b"\x01\xff", "\\x01ff"),
    ],
)
def test_unrepresentable_cells_become_text_not_null_or_error(
    value: object, expected: str
) -> None:
    assert to_cell(value) == expected
