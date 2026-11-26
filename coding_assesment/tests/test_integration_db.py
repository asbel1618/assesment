"""Real-PostgreSQL integration tests (marker: ``integration``).

Run with the compose ``db`` up and the root ``.env`` loaded::

    uv run --env-file ../.env pytest -m integration

Skipped when ``DATABASE_URL`` is unset or the server is unreachable. Data
tests run in a throwaway database created and dropped by the fixture, so the
compose database is never modified; the ``app_ro`` privilege tests only attempt
writes that must fail.
"""

import os
import uuid
from collections.abc import Iterator
from datetime import date
from decimal import Decimal

import pandas as pd
import pytest
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError, OperationalError

from app.cleaning import CLEAN_COLUMNS
from app.db.ports import QueryFailedError, QueryTimeoutError
from app.db.repository import MAX_ROWS, PostgresQueryRepository
from scripts.load_orders import load_clean_orders

pytestmark = pytest.mark.integration

PERMISSION_DENIED = "42501"
READ_ONLY_TRANSACTION = "25006"


def _sqlstate(exc: DBAPIError) -> str | None:
    return getattr(exc.orig, "sqlstate", None)


def _order(day: int, customer: str, country: str, amount: str, status: str) -> dict:
    return {
        "order_date": date(2025, 3, day),
        "customer": customer,
        "country": country,
        "product": "Laptop",
        "amount": Decimal(amount),
        "status": status,
    }


def _frame(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=list(CLEAN_COLUMNS), dtype=object)


# Spain/March completed = 100.00 + 50.50; cancelled/pending/refunded never count.
# "Whale" only has a cancelled order, so it must stay out of the top customers.
FIXTURE_ROWS = [
    _order(1, "Spain Buyer", "Spain", "100.00", "completed"),
    _order(2, "Spain Buyer", "Spain", "50.50", "completed"),
    _order(3, "Spain Buyer", "Spain", "999.00", "cancelled"),
    _order(4, "Spain Buyer", "Spain", "999.00", "pending"),
    _order(5, "Spain Buyer", "Spain", "999.00", "refunded"),
    _order(6, "France Buyer", "France", "70.00", "completed"),
    {
        **_order(7, "France Buyer", "France", "30.00", "completed"),
        "order_date": date(2025, 4, 7),
    },
    *[
        _order(8, f"Big {i:02d}", "Italy", f"{1000 + i}.00", "completed")
        for i in range(10)
    ],
    _order(9, "Whale", "Italy", "99999.00", "cancelled"),
]


@pytest.fixture(scope="module")
def scratch_engine() -> Iterator[Engine]:
    url = os.environ.get("DATABASE_URL")
    if not url:
        pytest.skip("DATABASE_URL is not set")
    admin = create_engine(url, isolation_level="AUTOCOMMIT")
    name = f"orders_test_{uuid.uuid4().hex[:12]}"
    try:
        with admin.connect() as conn:
            conn.execute(text(f'CREATE DATABASE "{name}"'))
    except OperationalError as exc:
        admin.dispose()
        pytest.skip(f"PostgreSQL is unreachable: {exc.orig}")
    engine = create_engine(make_url(url).set(database=name))
    try:
        yield engine
    finally:
        engine.dispose()
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE "{name}" WITH (FORCE)'))
        admin.dispose()


@pytest.fixture
def loaded(scratch_engine: Engine) -> Engine:
    load_clean_orders(scratch_engine, _frame(FIXTURE_ROWS))
    return scratch_engine


def _rows(engine: Engine, sql: str) -> list[tuple]:
    with engine.connect() as conn:
        return [tuple(r) for r in conn.exec_driver_sql(sql).fetchall()]


def test_sales_view_sums_completed_orders_per_month_and_country(loaded: Engine) -> None:
    rows = _rows(
        loaded,
        "SELECT month, country, total_amount, order_count "
        "FROM v_sales_by_month_country WHERE country IN ('Spain', 'France') "
        "ORDER BY country, month",
    )

    assert rows == [
        ("2025-03", "France", Decimal("70.00"), 1),
        ("2025-04", "France", Decimal("30.00"), 1),
        ("2025-03", "Spain", Decimal("150.50"), 2),
    ]


def test_top_customers_view_has_ten_completed_only_best_first_with_tiebreak(
    loaded: Engine,
) -> None:
    rows = _rows(loaded, "SELECT customer, total_amount FROM v_top_customers")

    names = [r[0] for r in rows]
    assert names == [f"Big {i:02d}" for i in range(9, -1, -1)]
    assert "Whale" not in names


def test_top_customers_ties_are_broken_alphabetically(scratch_engine: Engine) -> None:
    # Twelve equal totals inserted in reverse: only an explicit tie-break yields
    # the alphabetical first ten (a random order matches with probability ~1e-8).
    rows = [
        _order(1, f"Tie {i:02d}", "Spain", "100.00", "completed")
        for i in range(12, 0, -1)
    ]
    load_clean_orders(scratch_engine, _frame(rows))

    names = [
        r[0] for r in _rows(scratch_engine, "SELECT customer FROM v_top_customers")
    ]

    assert names == [f"Tie {i:02d}" for i in range(1, 11)]


def test_top_customers_with_fewer_than_ten_returns_all(scratch_engine: Engine) -> None:
    load_clean_orders(scratch_engine, _frame(FIXTURE_ROWS[:2]))

    assert _rows(
        scratch_engine, "SELECT customer, total_amount FROM v_top_customers"
    ) == [("Spain Buyer", Decimal("150.50"))]


def test_loading_twice_does_not_duplicate_rows(scratch_engine: Engine) -> None:
    frame = _frame(FIXTURE_ROWS)

    first = load_clean_orders(scratch_engine, frame)
    second = load_clean_orders(scratch_engine, frame)

    assert first == second == len(FIXTURE_ROWS)
    assert _rows(scratch_engine, "SELECT count(*), min(id) FROM orders") == [
        (len(FIXTURE_ROWS), 1)
    ]


def test_loading_replaces_previous_contents(scratch_engine: Engine) -> None:
    load_clean_orders(scratch_engine, _frame(FIXTURE_ROWS))

    load_clean_orders(scratch_engine, _frame(FIXTURE_ROWS[:2]))

    assert _rows(scratch_engine, "SELECT count(*) FROM orders") == [(2,)]


def test_repository_write_fails_in_read_only_transaction_even_without_validator(
    loaded: Engine,
) -> None:
    repository = PostgresQueryRepository(loaded)  # owner role: only the txn protects us

    with pytest.raises(QueryFailedError) as exc:
        repository.run_select("DELETE FROM orders")

    assert READ_ONLY_TRANSACTION in exc.value.reason
    assert _rows(loaded, "SELECT count(*) FROM orders") == [(len(FIXTURE_ROWS),)]


def test_repository_aborts_statements_over_the_timeout(loaded: Engine) -> None:
    with pytest.raises(QueryTimeoutError):
        PostgresQueryRepository(loaded).run_select("SELECT pg_sleep(30)")


@pytest.mark.parametrize(
    ("count", "truncated"),
    [(MAX_ROWS - 1, False), (MAX_ROWS, False), (MAX_ROWS + 1, True)],
)
def test_repository_caps_rows_and_flags_truncation(
    loaded: Engine, count: int, truncated: bool
) -> None:
    result = PostgresQueryRepository(loaded).run_select(
        f"SELECT g FROM generate_series(1, {count}) AS g"
    )

    assert len(result.rows) == min(count, MAX_ROWS)
    assert result.truncated is truncated


def test_repository_passes_percent_and_colon_literals_through(loaded: Engine) -> None:
    result = PostgresQueryRepository(loaded).run_select(
        "SELECT 'a%s' AS p, ':word' AS c"
    )

    assert result.columns == ["p", "c"]
    assert result.rows == [["a%s", ":word"]]


@pytest.fixture
def app_ro_engine() -> Iterator[Engine]:
    url = os.environ.get("READONLY_DATABASE_URL")
    if not url:
        pytest.skip("READONLY_DATABASE_URL is not set")
    engine = create_engine(url)
    try:
        with engine.connect() as conn:
            exists = conn.exec_driver_sql("SELECT to_regclass('orders')").scalar_one()
    except OperationalError as exc:
        engine.dispose()
        pytest.skip(f"PostgreSQL is unreachable: {exc.orig}")
    if exists is None:
        engine.dispose()
        pytest.skip("orders table is not loaded in the compose database")
    yield engine
    engine.dispose()


@pytest.mark.parametrize(
    "statement",
    [
        (
            "INSERT INTO orders (order_date, customer, country, product, amount, status) "
            "VALUES ('2025-01-01', 'x', 'Spain', 'x', 1, 'completed')"
        ),
        "UPDATE orders SET amount = 0",
        "DELETE FROM orders",
        "TRUNCATE orders",
        "CREATE TABLE app_ro_probe (a int)",
        "CREATE TEMP TABLE app_ro_probe (a int)",
    ],
)
def test_app_ro_privileges_deny_writes_even_in_a_read_write_transaction(
    app_ro_engine: Engine, statement: str
) -> None:
    with (
        pytest.raises(DBAPIError) as exc,
        app_ro_engine.connect() as conn,
        conn.begin(),
    ):
        conn.exec_driver_sql("SET TRANSACTION READ WRITE")  # defeat the role default
        conn.exec_driver_sql(statement)

    assert _sqlstate(exc.value) == PERMISSION_DENIED


def test_app_ro_can_select_from_allowlisted_objects(app_ro_engine: Engine) -> None:
    repository = PostgresQueryRepository(app_ro_engine)

    for obj in ("orders", "v_sales_by_month_country", "v_top_customers"):
        assert repository.run_select(f"SELECT count(*) FROM {obj}").columns == ["count"]
