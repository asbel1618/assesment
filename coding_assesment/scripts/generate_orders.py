"""Generate a deterministic, deliberately dirty orders CSV.

Each base row receives at most one defect so reject counts stay explainable;
exact duplicates are then copied from the (possibly dirty) rows and shuffled.
"""

import argparse
import csv
import random
from collections.abc import Sequence
from pathlib import Path

from app.cleaning import COUNTRIES, VALID_STATUSES

COLUMNS = ("date", "customer", "country", "product", "amount", "status")
STATUS_WEIGHTS = (75, 10, 10, 5)
INVALID_STATUSES = ("shipped", "COMPLETED?", "unknown")
# product -> (min, max) unit price in cents
PRODUCTS = {
    "Laptop": (80_000, 220_000),
    "Monitor": (15_000, 60_000),
    "Keyboard": (2_000, 15_000),
    "Mouse": (1_000, 8_000),
    "Headset": (3_000, 25_000),
    "Webcam": (4_000, 18_000),
    "Dock": (8_000, 30_000),
    "Tablet": (25_000, 90_000),
    "Printer": (10_000, 50_000),
    "Router": (5_000, 20_000),
}
FIRST_NAMES = (
    "Ana", "Luis", "Marta", "Pedro", "Sofia", "Carlos", "Elena", "Jorge",
    "Lucia", "Diego", "Clara", "Hugo", "Irene", "Pablo", "Laura", "Mateo",
    "Nora", "Raul", "Eva", "Ivan",
)  # fmt: skip
LAST_NAMES = (
    "Garcia", "Martin", "Lopez", "Silva", "Rossi", "Muller", "Dubois",
    "Smith", "Perez", "Costa",
)  # fmt: skip
MONTHS_ABBR = (
    "Jan", "Feb", "Mar", "Apr", "May", "Jun",
    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
)  # fmt: skip
INVALID_DATES = (
    "2025-13-45",
    "2025/02/30",
    "2O25-03-01",
    "n/a",
    "2025-00-10",
    "31/02/2025",
)
MISSING_AMOUNTS = ("", "N/A")

YEAR = 2025
DAYS_IN_MONTH = (31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)
# Cumulative thresholds over one uniform draw: (upper bound, defect name).
DEFECT_THRESHOLDS = (
    (0.10, "date_format"),
    (0.14, "invalid_date"),
    (0.17, "missing_amount"),
    (0.20, "formatted_amount"),
    (0.26, "country_variant"),
    (0.28, "invalid_status"),
)
DUPLICATE_RATE = 0.08

Row = dict[str, str]


def _customers(rng: random.Random) -> tuple[list[str], list[int]]:
    names = [f"{f} {last}" for f in FIRST_NAMES for last in LAST_NAMES]
    rng.shuffle(names)
    names = names[:150]
    # Zipf-like skew so the top-10 customers are clearly separated.
    weights = [round(1000 / (i + 1)) for i in range(len(names))]
    return names, weights


def _cents(value: int) -> str:
    return f"{value // 100}.{value % 100:02d}"


def _date_variant(rng: random.Random, month: int, day: int) -> str:
    if rng.random() < 0.5:
        return f"{day:02d}/{month:02d}/{YEAR}"  # always DD/MM/YYYY
    return f"{MONTHS_ABBR[month - 1]} {day:02d}, {YEAR}"


def _country_variant(rng: random.Random, country: str) -> str:
    return rng.choice(
        (country.lower(), f"  {country.upper()} ", f"{country} ", f" {country}")
    )


def _base_row(
    rng: random.Random, customers: Sequence[str], weights: Sequence[int]
) -> tuple[Row, int, int]:
    month = rng.randint(1, 12)
    day = rng.randint(1, DAYS_IN_MONTH[month - 1])
    product = rng.choice(tuple(PRODUCTS))
    low, high = PRODUCTS[product]
    cents = rng.randint(low, high) * rng.choice((1, 1, 1, 2, 3))
    row = {
        "date": f"{YEAR}-{month:02d}-{day:02d}",
        "customer": rng.choices(customers, weights)[0],
        "country": rng.choice(COUNTRIES),
        "product": product,
        "amount": _cents(cents),
        "status": rng.choices(VALID_STATUSES, STATUS_WEIGHTS)[0],
    }
    return row, month, day


def _inject_defect(rng: random.Random, row: Row, month: int, day: int) -> None:
    draw = rng.random()
    for bound, defect in DEFECT_THRESHOLDS:
        if draw < bound:
            break
    else:
        return
    if defect == "date_format":
        row["date"] = _date_variant(rng, month, day)
    elif defect == "invalid_date":
        row["date"] = rng.choice(INVALID_DATES)
    elif defect == "missing_amount":
        row["amount"] = rng.choice(MISSING_AMOUNTS)
    elif defect == "formatted_amount":
        cents = rng.randint(100_000, 500_000)  # >= 1,000 so the comma appears
        row["amount"] = f"${cents // 100:,}.{cents % 100:02d}"
    elif defect == "country_variant":
        row["country"] = _country_variant(rng, row["country"])
    elif defect == "invalid_status":
        row["status"] = rng.choice(INVALID_STATUSES)


def generate_orders(seed: int, n_base: int = 1000) -> list[Row]:
    """Return dirty order rows; identical for identical (seed, n_base)."""
    rng = random.Random(seed)
    customers, weights = _customers(rng)
    rows: list[Row] = []
    for _ in range(n_base):
        row, month, day = _base_row(rng, customers, weights)
        _inject_defect(rng, row, month, day)
        rows.append(row)
    rows.extend(dict(r) for r in rng.sample(rows, round(n_base * DUPLICATE_RATE)))
    rng.shuffle(rows)
    return rows


def write_csv(rows: Sequence[Row], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def main(argv: Sequence[str] | None = None) -> None:
    default_out = Path(__file__).resolve().parent.parent / "data" / "orders_raw.csv"
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--rows", type=int, default=1000, help="base rows (pre-dupes)")
    parser.add_argument("--out", type=Path, default=default_out)
    args = parser.parse_args(argv)
    rows = generate_orders(args.seed, args.rows)
    write_csv(rows, args.out)
    print(f"wrote {len(rows)} rows to {args.out}")


if __name__ == "__main__":
    main()
