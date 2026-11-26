"""Pure cleaning of raw order rows (no I/O, no database).

Policy (see PLAN.md §0): normalize text, reject exact duplicates (keep first),
reject rows with an unparseable date/amount, unknown country or invalid status.
Nothing is imputed. Rejects keep their original raw values plus a ``reason``.
"""

import re
from datetime import date
from decimal import Decimal

import pandas as pd

COUNTRIES = (
    "Spain",
    "France",
    "Germany",
    "Italy",
    "Portugal",
    "UK",
    "USA",
    "Mexico",
)
VALID_STATUSES = ("completed", "pending", "cancelled", "refunded")
RAW_COLUMNS = ("date", "customer", "country", "product", "amount", "status")
CLEAN_COLUMNS = ("order_date", "customer", "country", "product", "amount", "status")

_COUNTRY_LOOKUP = {c.casefold(): c for c in COUNTRIES}
_MONTHS = {
    m: i
    for i, m in enumerate(
        (
            "jan",
            "feb",
            "mar",
            "apr",
            "may",
            "jun",
            "jul",
            "aug",
            "sep",
            "oct",
            "nov",
            "dec",
        ),
        start=1,
    )
}
_ISO = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")
_DMY = re.compile(r"^(\d{2})/(\d{2})/(\d{4})$")
_MON = re.compile(r"^([A-Za-z]{3}) (\d{2}), (\d{4})$")
_AMOUNT_GROUPED = re.compile(r"^\$?\d{1,3}(,\d{3})+(\.\d{1,2})?$")
_AMOUNT_PLAIN = re.compile(r"^\$?\d+(\.\d{1,2})?$")
_MISSING_AMOUNTS = {"", "n/a"}
_CENT = Decimal("0.01")


def _normalize(value: str) -> str:
    return " ".join(value.split())


def _parse_date(value: str) -> date | None:
    """Accept YYYY-MM-DD, DD/MM/YYYY and 'Mon DD, YYYY'; None if invalid."""
    if m := _ISO.match(value):
        year, month, day = int(m[1]), int(m[2]), int(m[3])
    elif m := _DMY.match(value):
        day, month, year = int(m[1]), int(m[2]), int(m[3])
    elif (m := _MON.match(value)) and m[1].lower() in _MONTHS:
        month, day, year = _MONTHS[m[1].lower()], int(m[2]), int(m[3])
    else:
        return None
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _parse_amount(value: str) -> tuple[Decimal | None, str | None]:
    """Return (amount, None) or (None, reason)."""
    if value.casefold() in _MISSING_AMOUNTS:
        return None, "missing_amount"
    if not (_AMOUNT_GROUPED.match(value) or _AMOUNT_PLAIN.match(value)):
        return None, "invalid_amount"
    return Decimal(value.lstrip("$").replace(",", "")).quantize(_CENT), None


def clean_orders(raw: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Split raw orders into ``(clean, rejects)``.

    ``raw`` must be all-string with ``RAW_COLUMNS`` (read CSVs with
    ``dtype=str, keep_default_na=False``). The input is not modified.
    ``len(clean) + len(rejects) == len(raw)``.
    """
    missing = [c for c in RAW_COLUMNS if c not in raw.columns]
    if missing:
        raise ValueError(f"missing columns: {', '.join(missing)}")

    raw = raw.loc[:, list(RAW_COLUMNS)].reset_index(drop=True)
    norm = raw.apply(lambda col: col.map(_normalize))

    dup_key = norm.assign(
        country=norm["country"].str.casefold(), status=norm["status"].str.casefold()
    )
    is_dup = dup_key.duplicated(keep="first")

    records: list[dict[str, object]] = []
    reasons: list[str] = []
    for i, row in norm.iterrows():
        if is_dup[i]:
            records.append({})
            reasons.append("duplicate")
            continue
        found: list[str] = []
        order_date = _parse_date(row["date"])
        if order_date is None:
            found.append("invalid_date")
        amount, amount_reason = _parse_amount(row["amount"])
        if amount_reason:
            found.append(amount_reason)
        country = _COUNTRY_LOOKUP.get(row["country"].casefold())
        if country is None:
            found.append("invalid_country")
        status = row["status"].casefold()
        if status not in VALID_STATUSES:
            found.append("invalid_status")
        if not row["customer"]:
            found.append("missing_customer")
        if not row["product"]:
            found.append("missing_product")
        records.append(
            {}
            if found
            else {
                "order_date": order_date,
                "customer": row["customer"],
                "country": country,
                "product": row["product"],
                "amount": amount,
                "status": status,
            }
        )
        reasons.append(";".join(found))

    rejected = pd.Series([bool(r) for r in reasons], index=raw.index)
    clean = pd.DataFrame(
        [r for r in records if r], columns=list(CLEAN_COLUMNS), dtype=object
    )
    rejects = raw[rejected].assign(reason=[r for r in reasons if r])
    return clean, rejects.reset_index(drop=True)
