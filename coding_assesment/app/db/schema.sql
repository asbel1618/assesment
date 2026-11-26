-- orders table (data contract: PLAN.md §0). Constraints make the cleaning contract explicit.
CREATE TABLE IF NOT EXISTS orders (
    id         BIGSERIAL PRIMARY KEY,
    order_date DATE          NOT NULL,
    customer   TEXT          NOT NULL,
    country    TEXT          NOT NULL,
    product    TEXT          NOT NULL,
    amount     NUMERIC(12,2) NOT NULL CHECK (amount >= 0),
    status     TEXT          NOT NULL
               CHECK (status IN ('completed', 'pending', 'cancelled', 'refunded'))
);
