-- "Sales" = orders with status 'completed' only. Pending, cancelled and refunded
-- orders are not revenue (data contract, PLAN.md section 0).
-- SELECT for app_ro comes from the default privileges in 01-readonly-role.sh.

CREATE OR REPLACE VIEW v_sales_by_month_country AS
SELECT to_char(order_date, 'YYYY-MM') AS month,
       country,
       sum(amount)                    AS total_amount,
       count(*)                       AS order_count
FROM orders
WHERE status = 'completed'
GROUP BY 1, 2;

CREATE OR REPLACE VIEW v_top_customers AS
SELECT customer,
       sum(amount) AS total_amount,
       count(*)    AS order_count
FROM orders
WHERE status = 'completed'
GROUP BY customer
ORDER BY total_amount DESC, customer  -- tie-break keeps the top 10 deterministic
LIMIT 10;
