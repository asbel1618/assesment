from datetime import date
from decimal import Decimal

import pandas as pd
import pytest

from app.cleaning import (
    CLEAN_COLUMNS,
    COUNTRIES,
    RAW_COLUMNS,
    VALID_STATUSES,
    clean_orders,
)
from scripts.generate_orders import generate_orders

VALID_ROW = {
    "date": "2025-03-01",
    "customer": "Ana Garcia",
    "country": "Spain",
    "product": "Laptop",
    "amount": "1200.50",
    "status": "completed",
}


def _df(*overrides: dict[str, str]) -> pd.DataFrame:
    rows = [{**VALID_ROW, **o} for o in overrides]
    return pd.DataFrame(rows, columns=list(RAW_COLUMNS), dtype=str)


def _reasons(rejects: pd.DataFrame) -> list[str]:
    return rejects["reason"].tolist()


def test_exact_duplicate_is_rejected_keeping_first():
    clean, rejects = clean_orders(_df({}, {}))
    assert len(clean) == 1
    assert _reasons(rejects) == ["duplicate"]


def test_duplicates_differing_in_whitespace_and_case_collapse():
    clean, rejects = clean_orders(
        _df({}, {"country": "  SPAIN ", "customer": " Ana  Garcia"})
    )
    assert len(clean) == 1
    assert _reasons(rejects) == ["duplicate"]


@pytest.mark.parametrize("raw", ["2025-03-01", "01/03/2025", "Mar 01, 2025"])
def test_valid_date_formats_are_parsed(raw: str):
    clean, rejects = clean_orders(_df({"date": raw}))
    assert rejects.empty
    assert clean["order_date"].iloc[0] == date(2025, 3, 1)


@pytest.mark.parametrize(
    "raw",
    ["2025-13-45", "2025/02/30", "2O25-03-01", "n/a", "31/02/2025", "2025-00-10", ""],
)
def test_invalid_dates_are_rejected(raw: str):
    clean, rejects = clean_orders(_df({"date": raw}))
    assert clean.empty
    assert _reasons(rejects) == ["invalid_date"]


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("1200.50", Decimal("1200.50")),
        ("$1,200.50", Decimal("1200.50")),
        ("15", Decimal("15.00")),
    ],
)
def test_valid_amounts_are_parsed(raw: str, expected: Decimal):
    clean, rejects = clean_orders(_df({"amount": raw}))
    assert rejects.empty
    assert clean["amount"].iloc[0] == expected


@pytest.mark.parametrize(
    ("raw", "reason"),
    [
        ("", "missing_amount"),
        ("N/A", "missing_amount"),
        ("n/a", "missing_amount"),
        ("abc", "invalid_amount"),
        ("-5.00", "invalid_amount"),
        ("1,2,3", "invalid_amount"),
        ("12.345", "invalid_amount"),
    ],
)
def test_bad_amounts_are_rejected(raw: str, reason: str):
    clean, rejects = clean_orders(_df({"amount": raw}))
    assert clean.empty
    assert _reasons(rejects) == [reason]


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("spain", "Spain"), ("  SPAIN ", "Spain"), ("Spain ", "Spain"), ("uk", "UK")],
)
def test_country_variants_are_canonicalized(raw: str, expected: str):
    clean, rejects = clean_orders(_df({"country": raw}))
    assert rejects.empty
    assert clean["country"].iloc[0] == expected


def test_unknown_country_is_rejected():
    clean, rejects = clean_orders(_df({"country": "Atlantis"}))
    assert clean.empty
    assert _reasons(rejects) == ["invalid_country"]


def test_status_is_lowercased_and_invalid_rejected():
    clean, rejects = clean_orders(
        _df({"status": "Completed "}, {"status": "shipped"}, {"status": "COMPLETED?"})
    )
    assert clean["status"].tolist() == ["completed"]
    assert _reasons(rejects) == ["invalid_status", "invalid_status"]


def test_empty_customer_and_product_are_rejected():
    _, rejects = clean_orders(_df({"customer": " "}, {"product": ""}))
    assert _reasons(rejects) == ["missing_customer", "missing_product"]


def test_multiple_reasons_are_joined_in_fixed_order():
    _, rejects = clean_orders(_df({"amount": "", "date": "n/a"}))
    assert _reasons(rejects) == ["invalid_date;missing_amount"]


def test_rejects_keep_original_raw_values():
    _, rejects = clean_orders(_df({"country": "  Atlantis ", "amount": "$1,200.50"}))
    assert rejects["country"].iloc[0] == "  Atlantis "
    assert rejects["amount"].iloc[0] == "$1,200.50"


def test_input_is_not_mutated_and_output_columns_match_contract():
    raw = _df({"country": " spain"}, {})
    before = raw.copy()
    clean, rejects = clean_orders(raw)
    pd.testing.assert_frame_equal(raw, before)
    assert tuple(clean.columns) == CLEAN_COLUMNS
    assert tuple(rejects.columns) == (*RAW_COLUMNS, "reason")
    assert list(clean.index) == list(range(len(clean)))


def test_missing_input_column_raises():
    with pytest.raises(ValueError, match="amount"):
        clean_orders(_df({}).drop(columns=["amount"]))


def test_generator_output_is_cleaned_consistently():
    raw = pd.DataFrame(generate_orders(42), columns=list(RAW_COLUMNS), dtype=str)
    clean, rejects = clean_orders(raw)

    assert len(clean) + len(rejects) == len(raw)
    assert set(clean["country"]) <= set(COUNTRIES)
    assert set(clean["status"]) <= set(VALID_STATUSES)
    assert all(date(2025, 1, 1) <= d <= date(2025, 12, 31) for d in clean["order_date"])
    assert all(a >= 0 for a in clean["amount"])

    seen = {r for reasons in rejects["reason"] for r in reasons.split(";")}
    assert {"duplicate", "invalid_date", "missing_amount", "invalid_status"} <= seen
    assert "invalid_country" not in seen
