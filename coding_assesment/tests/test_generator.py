import csv
import re
from collections import Counter
from pathlib import Path

from scripts.generate_orders import (
    COLUMNS,
    COUNTRIES,
    VALID_STATUSES,
    generate_orders,
    main,
)

ISO = re.compile(r"^\d{4}-\d{2}-\d{2}$")
DMY = re.compile(r"^\d{2}/\d{2}/\d{4}$")
MON = re.compile(r"^[A-Z][a-z]{2} \d{2}, \d{4}$")
PLAIN_AMOUNT = re.compile(r"^\d+\.\d{2}$")
CURRENCY_AMOUNT = re.compile(r"^\$[\d,]+\.\d{2}$")


def test_same_seed_is_deterministic_and_other_seed_differs():
    assert generate_orders(7) == generate_orders(7)
    assert generate_orders(7) != generate_orders(8)


def test_row_count_and_columns():
    rows = generate_orders(42)
    assert len(rows) >= 1000
    assert all(tuple(r) == COLUMNS for r in rows)


def test_every_defect_type_is_present():
    rows = generate_orders(42)
    counts = Counter(tuple(r.values()) for r in rows)
    canonical = {c.lower() for c in COUNTRIES}

    assert sum(n - 1 for n in counts.values()) > 0, "no duplicates"
    assert any(DMY.match(r["date"]) for r in rows), "no DD/MM/YYYY dates"
    assert any(MON.match(r["date"]) for r in rows), "no 'Mon DD, YYYY' dates"
    assert any(
        not (ISO.match(r["date"]) or DMY.match(r["date"]) or MON.match(r["date"]))
        or r["date"] in {"2025-13-45", "2025-00-10"}
        for r in rows
    ), "no invalid dates"
    assert any(r["amount"].strip() in {"", "N/A"} for r in rows), "no missing amounts"
    assert any(CURRENCY_AMOUNT.match(r["amount"]) for r in rows), "no $ amounts"
    assert any(PLAIN_AMOUNT.match(r["amount"]) for r in rows)
    assert any(
        r["country"] not in COUNTRIES and r["country"].strip().lower() in canonical
        for r in rows
    ), "no country variants"
    assert any(r["country"] != r["country"].strip() for r in rows), "no whitespace"
    assert any(r["status"] not in VALID_STATUSES for r in rows), "no invalid status"


def test_main_writes_byte_identical_files(tmp_path: Path):
    a, b = tmp_path / "a.csv", tmp_path / "b.csv"
    main(["--out", str(a)])
    main(["--out", str(b)])
    assert a.read_bytes() == b.read_bytes()
    with a.open(newline="", encoding="utf-8") as fh:
        assert len(list(csv.DictReader(fh))) >= 1000
