-- =====================================================================
-- 06_return_fraud_analysis.sql
-- Return behavior and fraud-risk analysis.
-- =====================================================================

-- Q22: Customers with return rate above 40% of their orders
-- Business question: Which customers return unusually often?
-- Expected output: Customers whose return-line count is more than 40% of their order count.
WITH orders AS (
    SELECT customer_id, COUNT(DISTINCT invoice_no) AS orders, ROUND(SUM(line_total), 2) AS revenue
    FROM fact_orders
    GROUP BY customer_id
),
returns AS (
    SELECT customer_id, COUNT(*) AS return_lines, ROUND(SUM(ABS(quantity) * unit_price), 2) AS returned_value
    FROM fact_returns
    GROUP BY customer_id
)
SELECT
    c.customer_id,
    c.name,
    c.email,
    c.city_tier,
    c.loyalty_tier,
    o.orders,
    COALESCE(r.return_lines, 0) AS return_lines,
    ROUND(100.0 * COALESCE(r.return_lines, 0) / NULLIF(o.orders, 0), 2) AS return_rate_pct,
    o.revenue,
    COALESCE(r.returned_value, 0) AS returned_value
FROM orders o
JOIN dim_customers c ON o.customer_id = c.customer_id
LEFT JOIN returns r ON o.customer_id = r.customer_id
WHERE 1.0 * COALESCE(r.return_lines, 0) / NULLIF(o.orders, 0) > 0.40
ORDER BY return_rate_pct DESC, returned_value DESC;

-- Q23: Returns that happened within 1 day of purchase
-- Business question: Which returns are suspiciously immediate?
-- Expected output: Return records matched to purchase date within one day.
SELECT
    r.return_id,
    r.original_invoice,
    r.customer_id,
    c.name,
    r.stock_code,
    p.description,
    r.quantity,
    r.unit_price,
    r.return_date,
    d.full_date AS purchase_date,
    CAST(julianday(date(r.return_date)) - julianday(d.full_date) AS INTEGER) AS days_to_return
FROM fact_returns r
JOIN dim_customers c ON r.customer_id = c.customer_id
JOIN dim_products p ON r.stock_code = p.stock_code
JOIN fact_orders o ON o.customer_id = r.customer_id AND o.product_id = p.product_id
JOIN dim_date d ON o.date_id = d.date_id
WHERE ABS(julianday(date(r.return_date)) - julianday(d.full_date)) <= 1
ORDER BY r.return_date DESC
LIMIT 100;

-- Q24: High-value return clustering by city tier and loyalty tier
-- Business question: Are expensive returns concentrated in specific customer groups?
-- Expected output: Return counts and returned value by city tier and loyalty tier.
SELECT
    c.city_tier,
    c.loyalty_tier,
    COUNT(*) AS return_lines,
    COUNT(DISTINCT r.customer_id) AS returning_customers,
    ROUND(SUM(ABS(r.quantity) * r.unit_price), 2) AS returned_value,
    ROUND(AVG(ABS(r.quantity) * r.unit_price), 2) AS avg_return_value
FROM fact_returns r
JOIN dim_customers c ON r.customer_id = c.customer_id
GROUP BY c.city_tier, c.loyalty_tier
HAVING AVG(ABS(r.quantity) * r.unit_price) >= (
    SELECT AVG(ABS(quantity) * unit_price) FROM fact_returns
)
ORDER BY returned_value DESC;
