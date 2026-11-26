"""Query-execution port: the contract the service depends on (no driver imports)."""

from dataclasses import dataclass
from typing import Protocol

from app.schemas import Cell


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


class QueryRepository(Protocol):
    def run_select(self, sql: str) -> QueryResult:
        """Execute validated ``sql``; raises ``QueryExecutionError``."""
        ...
