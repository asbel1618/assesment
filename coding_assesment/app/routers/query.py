"""POST /query: HTTP concerns only (request/response models, error mapping)."""

from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from app.db.repository import (
    DatabaseUnavailableError,
    QueryExecutionError,
    QueryTimeoutError,
)
from app.dependencies import get_query_service
from app.llm.base import (
    LLMError,
    LLMResponseError,
    LLMTimeoutError,
    LLMUnavailableError,
)
from app.schemas import ErrorResponse, QueryRequest, QueryResponse
from app.services.query_service import GeneratedSQLError, QueryService

router = APIRouter()

_ERROR_RESPONSES: dict[int | str, dict[str, type[ErrorResponse]]] = {
    status: {"model": ErrorResponse} for status in (400, 502, 503, 504)
}


def _error(
    status: int, code: str, message: str, sql: str | None = None
) -> JSONResponse:
    body = ErrorResponse(code=code, message=message, sql=sql)
    return JSONResponse(status_code=status, content=body.model_dump())


def _llm_error(exc: LLMError) -> JSONResponse:
    if isinstance(exc, LLMTimeoutError):
        return _error(504, "llm_timeout", exc.reason)
    if isinstance(exc, LLMResponseError):
        return _error(502, "llm_bad_response", exc.reason)
    if isinstance(exc, LLMUnavailableError):
        return _error(502, "llm_unavailable", exc.reason)
    return _error(502, "llm_error", exc.reason)


def _execution_error(exc: QueryExecutionError) -> JSONResponse:
    if isinstance(exc, QueryTimeoutError):
        return _error(504, "query_timeout", exc.reason)
    if isinstance(exc, DatabaseUnavailableError):
        return _error(503, "db_unavailable", exc.reason)
    return _error(500, "query_error", exc.reason)


@router.post("/query", response_model=QueryResponse, responses=_ERROR_RESPONSES)
def query(
    request: QueryRequest,
    service: Annotated[QueryService, Depends(get_query_service)],
) -> QueryResponse | JSONResponse:
    try:
        answer = service.answer(request.question)
    except GeneratedSQLError as exc:
        return _error(400, exc.code, exc.reason, exc.sql)
    except LLMError as exc:
        return _llm_error(exc)
    except QueryExecutionError as exc:
        return _execution_error(exc)
    return QueryResponse(
        question=request.question,
        sql=answer.sql,
        columns=answer.columns,
        rows=answer.rows,
        truncated=answer.truncated,
    )
