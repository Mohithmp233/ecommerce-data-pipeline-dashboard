-- =====================================================================
-- 01_revenue_analysis.sql
-- Revenue and order trend analysis.
-- =====================================================================

-- Q1: Monthly revenue trend with MoM % growth
-- Business question: Is revenue growing month over month?
-- Expected output: One row per month with revenue, orders, AOV and MoM growth percentage.
WITH monthly AS (
    SELECT
        d.year,
        d.month,
        printf('%04d-%02d', d.year, d.month) AS year_month,
        ROUND(SUM(o.line_total), 2) AS revenue,
        COUNT(DISTINCT o.invoice_no) AS orders,
        ROUND(SUM(o.line_total) / NULLIF(COUNT(DISTINCT o.invoice_no), 0), 2) AS avg_order_value
    FROM fact_orders o
    JOIN dim_date d ON o.date_id = d.date_id
    GROUP BY d.year, d.month
)
SELECT
    year_month,
    revenue,
    orders,
    avg_order_value,
    ROUND(
        100.0 * (revenue - LAG(revenue) OVER (ORDER BY year, month))
        / NULLIF(LAG(revenue) OVER (ORDER BY year, month), 0),
        2
    ) AS mom_growth_pct
FROM monthly
ORDER BY year, month;

-- Q2: Revenue by country - top 15 with % of total
-- Business question: Which countries contribute most to revenue?
-- Expected output: Top 15 countries ranked by revenue with percentage contribution.
WITH country_revenue AS (
    SELECT
        c.country,
        ROUND(SUM(o.line_total), 2) AS revenue,
        COUNT(DISTINCT o.invoice_no) AS orders
    FROM fact_orders o
    JOIN dim_customers c ON o.customer_id = c.customer_id
    GROUP BY c.country
)
SELECT
    country,
    revenue,
    orders,
    ROUND(100.0 * revenue / NULLIF(SUM(revenue) OVER (), 0), 2) AS pct_of_total,
    RANK() OVER (ORDER BY revenue DESC) AS revenue_rank
FROM country_revenue
ORDER BY revenue DESC
LIMIT 15;

-- Q3: Best performing day of week and hour of day
-- Business question: When do customers place the highest-value orders?
-- Expected output: Revenue by day/hour plus subtotal rows that emulate a rollup.
WITH base AS (
    SELECT
        d.day_of_week,
        CAST(strftime('%H', o.extraction_timestamp) AS INTEGER) AS order_hour,
        ROUND(SUM(o.line_total), 2) AS revenue,
        COUNT(DISTINCT o.invoice_no) AS orders
    FROM fact_orders o
    JOIN dim_date d ON o.date_id = d.date_id
    GROUP BY d.day_of_week, order_hour
),
day_total AS (
    SELECT day_of_week, NULL AS order_hour, SUM(revenue) AS revenue, SUM(orders) AS orders
    FROM base
    GROUP BY day_of_week
),
grand_total AS (
    SELECT 'ALL_DAYS' AS day_of_week, NULL AS order_hour, SUM(revenue) AS revenue, SUM(orders) AS orders
    FROM base
)
SELECT day_of_week, order_hour, revenue, orders, 'day_hour' AS row_type FROM base
UNION ALL
SELECT day_of_week, order_hour, revenue, orders, 'day_total' AS row_type FROM day_total
UNION ALL
SELECT day_of_week, order_hour, revenue, orders, 'grand_total' AS row_type FROM grand_total
ORDER BY revenue DESC;

-- Q4: Quarterly revenue comparison - current vs previous year
-- Business question: Are quarters performing better than the same quarter last year?
-- Expected output: Revenue by year/quarter with previous-year revenue and YoY growth.
WITH quarterly AS (
    SELECT
        d.year,
        d.quarter,
        ROUND(SUM(o.line_total), 2) AS revenue,
        COUNT(DISTINCT o.invoice_no) AS orders
    FROM fact_orders o
    JOIN dim_date d ON o.date_id = d.date_id
    GROUP BY d.year, d.quarter
)
SELECT
    year,
    quarter,
    revenue,
    orders,
    LAG(revenue) OVER (PARTITION BY quarter ORDER BY year) AS previous_year_revenue,
    ROUND(
        100.0 * (revenue - LAG(revenue) OVER (PARTITION BY quarter ORDER BY year))
        / NULLIF(LAG(revenue) OVER (PARTITION BY quarter ORDER BY year), 0),
        2
    ) AS yoy_growth_pct
FROM quarterly
ORDER BY year, quarter;

-- Q5: Running total revenue by month
-- Business question: How much cumulative revenue has the business generated over time?
-- Expected output: Monthly revenue with cumulative running revenue.
WITH monthly AS (
    SELECT
        d.year,
        d.month,
        printf('%04d-%02d', d.year, d.month) AS year_month,
        ROUND(SUM(o.line_total), 2) AS revenue
    FROM fact_orders o
    JOIN dim_date d ON o.date_id = d.date_id
    GROUP BY d.year, d.month
)
SELECT
    year_month,
    revenue,
    ROUND(SUM(revenue) OVER (ORDER BY year, month), 2) AS running_total_revenue
FROM monthly
ORDER BY year, month;
