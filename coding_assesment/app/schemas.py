"""Pydantic request/response models of the HTTP API."""

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, StringConstraints

# Values a SELECT over the allowlisted objects can return. Decimal is serialized
# as a JSON string so money stays exact.
Cell = str | int | float | Decimal | date | datetime | bool | None


class QueryRequest(BaseModel):
    question: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)
    ]


class QueryResponse(BaseModel):
    question: str
    sql: str
    columns: list[str]
    rows: list[list[Cell]]
    truncated: bool


class ErrorResponse(BaseModel):
    code: str
    message: str
    sql: str | None = None
