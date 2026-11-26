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
INSERT_SQL = text(
    "INSERT INTO orders (order_date, customer, country, product, amount, status) "
    "VALUES (:order_date, :customer, :country, :product, :amount, :status)"
)


def load_clean_orders(engine: Engine, clean: pd.DataFrame) -> int:
    """Replace the contents of ``orders`` in one transaction; return the row count."""
    with engine.begin() as conn:
        conn.execute(text(SCHEMA_SQL.read_text(encoding="utf-8")))
        # TRUNCATE (not DROP) so dependent views (step 4) survive reloads.
        conn.execute(text("TRUNCATE orders RESTART IDENTITY"))
        if not clean.empty:
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

    loaded = load_clean_orders(create_engine_from_env("DATABASE_URL"), clean)

    print(f"read:     {len(raw)}")
    print(f"rejected: {len(rejects)} -> {args.rejects}")
    by_reason = rejects["reason"].str.split(";").explode().value_counts()
    for reason, count in by_reason.items():
        print(f"  {reason}: {count}")
    print(f"loaded:   {loaded}")


if __name__ == "__main__":
    main()
