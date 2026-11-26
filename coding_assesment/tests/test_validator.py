import pytest

from app.validator import InvalidSQLError, validate_sql

VALID_QUERIES = [
    "SELECT * FROM orders",
    "SELECT * FROM v_sales_by_month_country",
    "SELECT * FROM v_top_customers",
    "SELECT * FROM orders;",
    "SELECT * FROM Orders",
    "SELECT sum(amount) FROM orders WHERE status = 'completed' AND country = 'Spain'",
    (
        "SELECT to_char(order_date, 'YYYY-MM') AS month, country, round(sum(amount), 2) "
        "FROM orders GROUP BY 1, 2 ORDER BY 3 DESC LIMIT 5"
    ),
    "SELECT extract(month FROM order_date), count(DISTINCT customer) FROM orders GROUP BY 1",
    (
        "SELECT o.customer, t.total_amount FROM orders o "
        "JOIN v_top_customers t ON t.customer = o.customer"
    ),
    "WITH c AS (SELECT * FROM orders) SELECT count(*) FROM c",
    "SELECT * FROM (SELECT country FROM orders) AS s",
    "SELECT * FROM orders WHERE customer IN (SELECT customer FROM v_top_customers)",
    "SELECT customer FROM orders UNION SELECT customer FROM v_top_customers",
    "SELECT * FROM orders WHERE customer = 'a -- b'",
]

INVALID_QUERIES = [
    ("", "empty query"),
    ("   ", "empty query"),
    (";", "empty query"),
    ("hello world how are you", "could not parse"),
    ("Total sales", "only SELECT"),
    ("DROP TABLE orders", "only SELECT"),
    ("UPDATE orders SET amount = 0", "only SELECT"),
    ("INSERT INTO orders (customer) VALUES ('x')", "only SELECT"),
    ("DELETE FROM orders", "only SELECT"),
    ("COPY orders TO '/tmp/x'", "only SELECT"),
    ("EXPLAIN SELECT * FROM orders", "only SELECT"),
    ("VALUES (1)", "only SELECT"),
    ("SELECT 1; DROP TABLE orders", "multiple statements"),
    ("SELECT * FROM orders; SELECT * FROM orders", "multiple statements"),
    ("SELECT * INTO t FROM orders", "INTO"),
    ("SELECT * FROM orders FOR UPDATE", "locking"),
    (
        "WITH x AS (DELETE FROM orders RETURNING *) SELECT * FROM x",
        "data-modifying",
    ),
    ("SELECT * FROM pg_catalog.pg_user", "schema-qualified"),
    ("SELECT * FROM information_schema.tables", "schema-qualified"),
    ("SELECT * FROM public.orders", "schema-qualified"),
    ("SELECT * FROM pg_user", "table not allowed: pg_user"),
    ('SELECT * FROM "ORDERS"', "table not allowed: ORDERS"),
    ("SELECT * FROM (SELECT * FROM pg_user) s", "table not allowed: pg_user"),
    ("SELECT (SELECT usename FROM pg_user)", "table not allowed: pg_user"),
    (
        "SELECT * FROM orders WHERE customer IN (SELECT rolname FROM pg_roles)",
        "table not allowed: pg_roles",
    ),
    (
        "WITH x AS (SELECT * FROM pg_user) SELECT * FROM x",
        "table not allowed: pg_user",
    ),
    (
        "WITH orders AS (SELECT * FROM secret) SELECT * FROM orders",
        "table not allowed: secret",
    ),
    (
        "SELECT * FROM (WITH pg_user AS (SELECT 1) SELECT * FROM pg_user) s, pg_user",
        "table not allowed: pg_user",
    ),
    ("SELECT pg_sleep(5)", "function not allowed: pg_sleep"),
    ("SELECT pg_catalog.pg_sleep(5)", "function not allowed: pg_sleep"),
    ("SELECT set_config('a', 'b', false)", "function not allowed: set_config"),
    ("SELECT current_setting('x')", "function not allowed: current_setting"),
    ("SELECT lo_import('/etc/passwd')", "function not allowed: lo_import"),
    ("SELECT * FROM pg_read_file('/etc/passwd')", "table functions"),
    (
        "SELECT * FROM orders o, LATERAL pg_ls_dir('.') d",
        "function not allowed: pg_ls_dir",
    ),
    ("SELECT * FROM generate_series(1, 3)", "table functions"),
    ("SELECT * FROM orders -- hi", "comments"),
    ("SELECT /* x */ * FROM orders", "comments"),
]


@pytest.mark.parametrize("sql", VALID_QUERIES)
def test_valid_queries_are_accepted(sql: str):
    assert isinstance(validate_sql(sql), str)


@pytest.mark.parametrize(("sql", "reason"), INVALID_QUERIES)
def test_invalid_queries_are_rejected_with_reason(sql: str, reason: str):
    with pytest.raises(InvalidSQLError) as exc:
        validate_sql(sql)
    assert reason in exc.value.reason


def test_returned_sql_is_normalized_single_statement():
    assert validate_sql("SELECT * FROM Orders;") == "SELECT * FROM orders"
