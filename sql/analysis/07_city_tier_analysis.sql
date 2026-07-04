-- =====================================================================
-- 07_city_tier_analysis.sql
-- City-tier performance and demand analysis.
-- =====================================================================

-- Q25: Revenue, AOV and repeat rate by city tier
-- Business question: Which city tiers drive the strongest revenue and repeat purchasing?
-- Expected output: City-tier revenue, active customers, AOV and repeat customer rate.
WITH customer_orders AS (
    SELECT
        c.city_tier,
        o.customer_id,
        COUNT(DISTINCT o.invoice_no) AS orders,
        SUM(o.line_total) AS revenue
    FROM fact_orders o
    JOIN dim_customers c ON o.customer_id = c.customer_id
    GROUP BY c.city_tier, o.customer_id
)
SELECT
    city_tier,
    COUNT(DISTINCT customer_id) AS active_customers,
    ROUND(SUM(revenue), 2) AS revenue,
    SUM(orders) AS orders,
    ROUND(SUM(revenue) / NULLIF(SUM(orders), 0), 2) AS avg_order_value,
    ROUND(100.0 * SUM(CASE WHEN orders > 1 THEN 1 ELSE 0 END) / NULLIF(COUNT(*), 0), 2) AS repeat_rate_pct
FROM customer_orders
GROUP BY city_tier
ORDER BY revenue DESC;

-- Q26: City tier churn risk - percent customers inactive 60+ days
-- Business question: Which city tiers have the highest inactive customer share?
-- Expected output: City-tier inactive customer counts and churn-risk percentage.
WITH last_order AS (
    SELECT
        o.customer_id,
        MAX(d.full_date) AS last_order_date,
        CAST(julianday((SELECT MAX(full_date) FROM dim_date)) - julianday(MAX(d.full_date)) AS INTEGER) AS days_inactive
    FROM fact_orders o
    JOIN dim_date d ON o.date_id = d.date_id
    GROUP BY o.customer_id
)
SELECT
    c.city_tier,
    COUNT(*) AS active_customers,
    SUM(CASE WHEN lo.days_inactive >= 60 THEN 1 ELSE 0 END) AS inactive_60d_customers,
    ROUND(100.0 * SUM(CASE WHEN lo.days_inactive >= 60 THEN 1 ELSE 0 END) / NULLIF(COUNT(*), 0), 2) AS churn_risk_pct,
    ROUND(AVG(lo.days_inactive), 1) AS avg_days_inactive
FROM last_order lo
JOIN dim_customers c ON lo.customer_id = c.customer_id
GROUP BY c.city_tier
ORDER BY churn_risk_pct DESC;

-- Q27: Best product categories by city tier
-- Business question: Which categories should be emphasized for each city tier?
-- Expected output: Category ranking within each city tier by revenue.
WITH category_sales AS (
    SELECT
        c.city_tier,
        p.category,
        ROUND(SUM(o.line_total), 2) AS revenue,
        SUM(o.quantity) AS units_sold,
        COUNT(DISTINCT o.invoice_no) AS orders
    FROM fact_orders o
    JOIN dim_customers c ON o.customer_id = c.customer_id
    JOIN dim_products p ON o.product_id = p.product_id
    GROUP BY c.city_tier, p.category
)
SELECT
    city_tier,
    category,
    revenue,
    units_sold,
    orders,
    RANK() OVER (PARTITION BY city_tier ORDER BY revenue DESC) AS category_rank
FROM category_sales
ORDER BY city_tier, category_rank;
