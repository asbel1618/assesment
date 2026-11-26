"""Pure validation of LLM-generated SQL (no I/O, no database).

Closed-world policy: a query is accepted only if it is a single read-only
SELECT over the allowlisted tables/views (unqualified names) and uses only
functions that sqlglot models natively. Anything else is rejected, so an
unknown construct fails safe. The ``app_ro`` role is the second layer.
"""

import sqlglot
from sqlglot import exp
from sqlglot.errors import SqlglotError
from sqlglot.optimizer.normalize_identifiers import normalize_identifiers
from sqlglot.optimizer.scope import traverse_scope

ALLOWED_TABLES = frozenset({"orders", "v_sales_by_month_country", "v_top_customers"})
# Functions sqlglot does not model (parsed as exp.Anonymous) that are still safe.
# Empty on purpose: add a name here only when a real question needs it.
ALLOWED_EXTRA_FUNCTIONS: frozenset[str] = frozenset()

_DIALECT = "postgres"
_WRITE_NODES = (exp.Insert, exp.Update, exp.Delete, exp.Merge)


class InvalidSQLError(ValueError):
    """The SQL violates the validation policy; ``reason`` is safe to show."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def validate_sql(sql: str) -> str:
    """Return the normalized SQL, or raise ``InvalidSQLError(reason)``."""
    try:
        statements = [s for s in sqlglot.parse(sql, read=_DIALECT) if s is not None]
    except SqlglotError as exc:
        raise InvalidSQLError("could not parse SQL") from exc

    if not statements:
        raise InvalidSQLError("empty query")
    if len(statements) > 1:
        raise InvalidSQLError("multiple statements are not allowed")

    ast = statements[0]
    if not isinstance(ast, exp.Select | exp.SetOperation):
        raise InvalidSQLError("only SELECT queries are allowed")

    _reject_unsafe_constructs(ast)
    ast = normalize_identifiers(ast, dialect=_DIALECT)
    _check_tables(ast)
    _check_functions(ast)
    return ast.sql(dialect=_DIALECT)


def _reject_unsafe_constructs(ast: exp.Expression) -> None:
    for node in ast.walk():
        if isinstance(node, _WRITE_NODES):
            raise InvalidSQLError("data-modifying statements are not allowed")
        if isinstance(node, exp.Into | exp.Lock):
            raise InvalidSQLError("SELECT INTO and locking clauses are not allowed")
        if node.comments:
            raise InvalidSQLError("comments are not allowed")


def _check_tables(ast: exp.Expression) -> None:
    # A name is a CTE reference only if a CTE of that name is visible in the
    # table's own scope; a CTE defined in one subquery must not mask a real
    # table (e.g. pg_user) referenced elsewhere.
    cte_refs = {
        id(table)
        for scope in traverse_scope(ast)
        for table in scope.tables
        if table.name in scope.cte_sources
    }
    for table in ast.find_all(exp.Table):
        if not isinstance(table.this, exp.Identifier):
            raise InvalidSQLError("table functions are not allowed")
        if table.db or table.catalog:
            raise InvalidSQLError("schema-qualified names are not allowed")
        if id(table) not in cte_refs and table.name not in ALLOWED_TABLES:
            raise InvalidSQLError(f"table not allowed: {table.name}")


def _check_functions(ast: exp.Expression) -> None:
    for func in ast.find_all(exp.Anonymous):
        if func.name.lower() not in ALLOWED_EXTRA_FUNCTIONS:
            raise InvalidSQLError(f"function not allowed: {func.name}")
