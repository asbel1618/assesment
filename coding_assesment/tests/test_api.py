"""POST /query tests. Hermetic: fake LLM and fake repository, no network, no Postgres.

Only the two leaf providers are overridden, so the real QueryService and the real
validator run: LLM output is untrusted and must be checked before it reaches the DB.
"""

from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from httpx import Response

from app.api import create_app
from app.db.repository import (
    DatabaseUnavailableError,
    QueryExecutionError,
    QueryFailedError,
    QueryResult,
    QueryTimeoutError,
)
from app.dependencies import get_llm_client, get_query_repository
from app.llm.base import (
    LLMError,
    LLMResponseError,
    LLMTimeoutError,
    LLMUnavailableError,
)
from app.validator import validate_sql

LLM_SQL = (
    "SELECT total_amount FROM v_sales_by_month_country "
    "WHERE country = 'Spain' AND month = '2025-03'"
)
RESULT = QueryResult(
    columns=["total_amount", "day"],
    rows=[[Decimal("8084.52"), date(2025, 3, 31)]],
    truncated=False,
)


class FakeLLM:
    def __init__(self, result: str | LLMError) -> None:
        self._result = result
        self.calls: list[str] = []

    def generate_sql(self, question: str) -> str:
        self.calls.append(question)
        if isinstance(self._result, LLMError):
            raise self._result
        return self._result


class FakeRepository:
    def __init__(self, result: QueryResult | QueryExecutionError = RESULT) -> None:
        self._result = result
        self.calls: list[str] = []

    def run_select(self, sql: str) -> QueryResult:
        self.calls.append(sql)
        if isinstance(self._result, QueryExecutionError):
            raise self._result
        return self._result


@pytest.fixture(autouse=True)
def _no_real_services(monkeypatch: pytest.MonkeyPatch) -> None:
    # If an override ever stops applying, the real providers fail loudly here
    # instead of reaching a live LLM or database.
    monkeypatch.delenv("LLM_BASE_URL", raising=False)
    monkeypatch.delenv("READONLY_DATABASE_URL", raising=False)


def _client(llm: FakeLLM, repository: FakeRepository) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_llm_client] = lambda: llm
    app.dependency_overrides[get_query_repository] = lambda: repository
    return TestClient(app)


def _ask(llm: FakeLLM, repository: FakeRepository, question: str = "q?") -> Response:
    return _client(llm, repository).post("/query", json={"question": question})


def test_happy_path_returns_rows() -> None:
    llm, repository = FakeLLM(LLM_SQL), FakeRepository()

    response = _ask(llm, repository, "  how much did we sell in Spain in March?  ")

    assert response.status_code == 200
    assert response.json() == {
        "question": "how much did we sell in Spain in March?",
        "sql": validate_sql(LLM_SQL),
        "columns": ["total_amount", "day"],
        "rows": [["8084.52", "2025-03-31"]],
        "truncated": False,
    }
    assert llm.calls == ["how much did we sell in Spain in March?"]
    assert repository.calls == [validate_sql(LLM_SQL)]


def test_invalid_sql_from_llm_is_rejected_before_execution() -> None:
    llm, repository = FakeLLM("DROP TABLE orders"), FakeRepository()

    response = _ask(llm, repository)

    assert response.status_code == 400
    body = response.json()
    assert body["code"] == "invalid_sql"
    assert body["message"]
    assert body["sql"] == "DROP TABLE orders"
    assert repository.calls == []


@pytest.mark.parametrize(
    ("error", "status", "code"),
    [
        (LLMUnavailableError("llm down"), 502, "llm_unavailable"),
        (LLMTimeoutError("llm slow"), 504, "llm_timeout"),
        (LLMResponseError("llm garbage"), 502, "llm_bad_response"),
    ],
)
def test_llm_errors_map_to_gateway_statuses(
    error: LLMError, status: int, code: str
) -> None:
    repository = FakeRepository()

    response = _ask(FakeLLM(error), repository)

    assert response.status_code == status
    assert response.json() == {"code": code, "message": error.reason, "sql": None}
    assert repository.calls == []


@pytest.mark.parametrize(
    ("error", "status", "code"),
    [
        (QueryFailedError("bad column"), 400, "query_failed"),
        (QueryTimeoutError("too slow"), 504, "query_timeout"),
        (DatabaseUnavailableError("db down"), 503, "db_unavailable"),
        (QueryExecutionError("boom"), 500, "query_error"),
    ],
)
def test_execution_errors_map_to_statuses(
    error: QueryExecutionError, status: int, code: str
) -> None:
    response = _ask(FakeLLM(LLM_SQL), FakeRepository(error))

    assert response.status_code == status
    body = response.json()
    assert body["code"] == code
    assert body["message"] == error.reason
    # Only a database-rejected statement echoes the SQL back.
    assert body["sql"] == (validate_sql(LLM_SQL) if code == "query_failed" else None)


@pytest.mark.parametrize(
    "payload",
    [{"question": ""}, {"question": "   "}, {}, {"question": "x" * 501}],
)
def test_invalid_question_is_422_and_never_reaches_the_llm(
    payload: dict[str, str],
) -> None:
    llm = FakeLLM(LLM_SQL)

    response = _client(llm, FakeRepository()).post("/query", json=payload)

    assert response.status_code == 422
    assert llm.calls == []


def test_ui_page_is_served() -> None:
    response = TestClient(create_app()).get("/ui")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "<title>" in response.text
