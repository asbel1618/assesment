"""Database engine factory. Connection URLs come from the environment only."""

import os

from sqlalchemy import Engine, create_engine


def create_engine_from_env(var: str) -> Engine:
    """Build an engine from the URL in environment variable ``var``."""
    url = os.environ.get(var)
    if not url:
        raise RuntimeError(f"environment variable {var} is not set")
    return create_engine(url, pool_pre_ping=True)
