"""Prompt construction. Describes only the allowlisted tables/views (PostgreSQL)."""

from app.cleaning import COUNTRIES, VALID_STATUSES

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

Rules:
- Reply with exactly one SELECT statement and nothing else: no explanation, no comments,
  no Markdown.
- Use only the objects listed above, unqualified (no schema prefix).
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
