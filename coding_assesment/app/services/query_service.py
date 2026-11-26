"""Orchestration: question -> LLM -> validate -> execute."""

from dataclasses import dataclass

from app.db.ports import QueryFailedError, QueryRepository
from app.llm.base import LLMClient
from app.schemas import Cell
from app.validator import InvalidSQLError, validate_sql


class GeneratedSQLError(Exception):
    """The LLM's SQL was rejected (by the validator or the database).

    Carries the offending SQL so the caller can see what the model produced.
    """

    def __init__(self, code: str, reason: str, sql: str) -> None:
        super().__init__(reason)
        self.code = code
        self.reason = reason
        self.sql = sql


@dataclass(frozen=True)
class QueryAnswer:
    sql: str
    columns: list[str]
    rows: list[list[Cell]]
    truncated: bool


class QueryService:
    def __init__(self, llm: LLMClient, repository: QueryRepository) -> None:
        self._llm = llm
        self._repository = repository

    def answer(self, question: str) -> QueryAnswer:
        raw_sql = self._llm.generate_sql(question)
        try:
            sql = validate_sql(raw_sql)
        except InvalidSQLError as exc:
            raise GeneratedSQLError("invalid_sql", exc.reason, raw_sql) from exc
        try:
            result = self._repository.run_select(sql)
        except QueryFailedError as exc:
            raise GeneratedSQLError("query_failed", exc.reason, sql) from exc
        return QueryAnswer(sql, result.columns, result.rows, result.truncated)
