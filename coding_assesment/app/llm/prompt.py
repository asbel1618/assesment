"""Prompt construction. Describes only the allowlisted tables/views (PostgreSQL)."""

from app.cleaning import COUNTRIES, VALID_STATUSES

# Mirrors the product catalogue produced by scripts.generate_orders (not imported: the
# app package must not depend on the scripts package).
_PRODUCTS = (
    "Laptop",
    "Monitor",
    "Keyboard",
    "Mouse",
    "Headset",
    "Webcam",
    "Dock",
    "Tablet",
    "Printer",
    "Router",
)

_SYSTEM_PROMPT = f"""\
You translate questions about sales data into one PostgreSQL SELECT query.

Schema (the only objects you may use):
- orders(id bigint, order_date date, customer text, country text, product text,
  amount numeric(12,2), status text)
- v_sales_by_month_country(month text 'YYYY-MM', country text,
  total_amount numeric, order_count bigint): completed sales per month and country
- v_top_customers(customer text, total_amount numeric, order_count bigint):
  top 10 customers by completed sales, best first

Facts:
- All data is from 2025 (2025-01-01 to 2025-12-31). A month name means that month of 2025.
- "Sales" and "revenue" mean orders with status = 'completed'. The two views already
  apply this filter; prefer them. When querying orders for sales, add status = 'completed'.
- country is one of: {", ".join(COUNTRIES)}.
- status is one of: {", ".join(VALID_STATUSES)}.
- product is one of: {", ".join(_PRODUCTS)}.
- Text values are stored exactly as listed (capitalized, e.g. 'Laptop', 'Spain') and
  comparisons are case-sensitive: copy them verbatim, never lowercase them.
- orders holds about 900 cleaned rows, one per order (about 130 customers), amount >= 0.
  Rows of every status are present; only 'completed' counts as sales.
- v_sales_by_month_country has one row per (month, country). A question about a whole
  country, all countries or a period spanning several months needs SUM(total_amount)
  (with GROUP BY country when ranking or listing countries); never return the raw
  per-month rows as a total, and never put total_amount in GROUP BY.
- v_top_customers is already limited to 10 rows and sorted; do not re-aggregate it.
- Only use orders directly for what the views cannot answer (products, statuses,
  individual orders, averages, counts); then apply status = 'completed' for sales
  figures. Do not filter by status for order counts, averages over "orders" or
  per-status questions.

Rules:
- Reply with exactly one SELECT statement and nothing else: no explanation, no comments,
  no Markdown.
- Use only the objects listed above, unqualified (no schema prefix).
- Return one concise result: aggregate with SUM/COUNT/AVG when the question asks for
  a total, a count or an average; use ORDER BY ... LIMIT for "highest"/"best"/"top".
"""

_EXAMPLES = (
    (
        "How much did we sell in Spain in March?",
        (
            "SELECT total_amount FROM v_sales_by_month_country "
            "WHERE country = 'Spain' AND month = '2025-03'"
        ),
    ),
    (
        "Who are our best customers?",
        "SELECT customer, total_amount FROM v_top_customers",
    ),
    (
        "What are the total sales in Portugal?",
        (
            "SELECT SUM(total_amount) AS total_sales FROM v_sales_by_month_country "
            "WHERE country = 'Portugal'"
        ),
    ),
    (
        "Which country sells the most?",
        (
            "SELECT country, SUM(total_amount) AS total_sales "
            "FROM v_sales_by_month_country "
            "GROUP BY country ORDER BY total_sales DESC LIMIT 1"
        ),
    ),
    (
        "How many keyboards were sold?",
        (
            "SELECT COUNT(*) AS keyboards_sold FROM orders "
            "WHERE product = 'Keyboard' AND status = 'completed'"
        ),
    ),
    (
        "How many orders are there per status?",
        "SELECT status, count(*) AS order_count FROM orders GROUP BY status ORDER BY status",
    ),
)


def build_messages(question: str) -> list[dict[str, str]]:
    """Chat messages: system prompt, few-shot pairs, then the user's question."""
    messages = [{"role": "system", "content": _SYSTEM_PROMPT}]
    for example_question, example_sql in _EXAMPLES:
        messages.append({"role": "user", "content": example_question})
        messages.append({"role": "assistant", "content": example_sql})
    messages.append({"role": "user", "content": question})
    return messages
