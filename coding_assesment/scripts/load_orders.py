"""Clean the raw orders CSV and load it into PostgreSQL (idempotent).

Run from ``coding_assesment/``: ``uv run --env-file ../.env python -m scripts.load_orders``.
Uses the owner role from ``DATABASE_URL``. Rejected rows go to a CSV with a ``reason``.
"""

import argparse
from collections.abc import Sequence
from pathlib import Path

import pandas as pd
from sqlalchemy import Engine, text

from app.cleaning import clean_orders
from app.db.connection import create_engine_from_env

ROOT = Path(__file__).resolve().parent.parent
SCHEMA_SQL = ROOT / "app" / "db" / "schema.sql"
VIEWS_SQL = ROOT / "app" / "db" / "views.sql"
INSERT_SQL = text(
    "INSERT INTO orders (order_date, customer, country, product, amount, status) "
    "VALUES (:order_date, :customer, :country, :product, :amount, :status)"
)


class EmptyLoadError(Exception):
    """Nothing survived cleaning; loading would truncate ``orders`` for no data."""


def load_clean_orders(engine: Engine, clean: pd.DataFrame) -> int:
    """Replace the contents of ``orders`` in one transaction; return the row count.

    Raises ``EmptyLoadError`` before touching the database if ``clean`` is empty.
    """
    if clean.empty:
        raise EmptyLoadError("no valid rows to load; refusing to truncate orders")
    with engine.begin() as conn:
        conn.execute(text(SCHEMA_SQL.read_text(encoding="utf-8")))
        conn.execute(text(VIEWS_SQL.read_text(encoding="utf-8")))
        # TRUNCATE (not DROP) so dependent views (step 4) survive reloads.
        conn.execute(text("TRUNCATE orders RESTART IDENTITY"))
        conn.execute(INSERT_SQL, clean.to_dict("records"))
        loaded = conn.execute(text("SELECT count(*) FROM orders")).scalar_one()
        if loaded != len(clean):
            raise RuntimeError(f"loaded {loaded} rows, expected {len(clean)}")
    return loaded


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=ROOT / "data" / "orders_raw.csv")
    parser.add_argument(
        "--rejects", type=Path, default=ROOT / "data" / "rejected_orders.csv"
    )
    args = parser.parse_args(argv)

    raw = pd.read_csv(args.input, dtype=str, keep_default_na=False)
    clean, rejects = clean_orders(raw)

    args.rejects.parent.mkdir(parents=True, exist_ok=True)
    rejects.to_csv(args.rejects, index=False)

    try:
        loaded = load_clean_orders(create_engine_from_env("DATABASE_URL"), clean)
    except EmptyLoadError as exc:
        raise SystemExit(
            f"error: {exc} (read {len(raw)}, rejected {len(rejects)})"
        ) from exc

    print(f"read:     {len(raw)}")
    print(f"rejected: {len(rejects)} -> {args.rejects}")
    if not rejects.empty:  # an empty frame has no string column to split
        by_reason = rejects["reason"].str.split(";").explode().value_counts()
        for reason, count in by_reason.items():
            print(f"  {reason}: {count}")
    print(f"loaded:   {loaded}")


if __name__ == "__main__":
    main()
