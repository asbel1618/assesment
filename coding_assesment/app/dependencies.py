"""FastAPI dependency providers. Built lazily so importing the app needs no env/network."""

from functools import lru_cache
from typing import Annotated

from fastapi import Depends

from app.db.repository import QueryRepository, create_query_repository_from_env
from app.llm.base import LLMClient
from app.llm.client import create_llm_client_from_env
from app.services.query_service import QueryService


@lru_cache
def get_llm_client() -> LLMClient:
    return create_llm_client_from_env()


@lru_cache
def get_query_repository() -> QueryRepository:
    return create_query_repository_from_env()


def get_query_service(
    llm: Annotated[LLMClient, Depends(get_llm_client)],
    repository: Annotated[QueryRepository, Depends(get_query_repository)],
) -> QueryService:
    return QueryService(llm, repository)
