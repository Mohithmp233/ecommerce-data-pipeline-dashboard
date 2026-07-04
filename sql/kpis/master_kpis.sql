-- =====================================================================
-- master_kpis.sql
-- Single-row KPI query for Streamlit, Excel and README insights.
-- =====================================================================

-- Query name: Master KPI Snapshot
-- Business question: What are the headline metrics for the current warehouse?
-- Expected output: One row with revenue, orders, customers, AOV, return rate and data quality.
WITH order_kpis AS (
    SELECT
        ROUND(SUM(line_total), 2) AS total_revenue,
        COUNT(DISTINCT invoice_no) AS total_orders,
        COUNT(DISTINCT customer_id) AS active_customers,
        ROUND(SUM(line_total) / NULLIF(COUNT(DISTINCT invoice_no), 0), 2) AS avg_order_value,
        ROUND(AVG(data_quality_score), 2) AS avg_data_quality_score
    FROM fact_orders
),
product_kpis AS (
    SELECT
        COUNT(*) AS total_products,
        SUM(CASE WHEN low_stock_flag = 1 THEN 1 ELSE 0 END) AS low_stock_products
    FROM dim_products
),
return_kpis AS (
    SELECT
        COUNT(*) AS return_lines,
        ROUND(SUM(ABS(quantity) * unit_price), 2) AS returned_value
    FROM fact_returns
),
top_category AS (
    SELECT p.category
    FROM fact_orders o
    JOIN dim_products p ON o.product_id = p.product_id
    GROUP BY p.category
    ORDER BY SUM(o.line_total) DESC
    LIMIT 1
),
churn AS (
    SELECT COUNT(*) AS churn_risk_customers
    FROM (
        SELECT
            o.customer_id,
            CAST(julianday((SELECT MAX(full_date) FROM dim_date)) - julianday(MAX(d.full_date)) AS INTEGER) AS days_inactive
        FROM fact_orders o
        JOIN dim_date d ON o.date_id = d.date_id
        GROUP BY o.customer_id
        HAVING days_inactive >= 90
    ) x
)
SELECT
    ok.total_revenue,
    ok.total_orders,
    ok.active_customers,
    pk.total_products,
    ok.avg_order_value,
    ROUND(100.0 * COALESCE(rk.return_lines, 0) / NULLIF(ok.total_orders, 0), 2) AS return_rate_pct,
    COALESCE((SELECT category FROM top_category), 'N/A') AS top_category,
    churn.churn_risk_customers,
    pk.low_stock_products,
    ok.avg_data_quality_score,
    COALESCE(rk.returned_value, 0) AS returned_value
FROM order_kpis ok
CROSS JOIN product_kpis pk
CROSS JOIN return_kpis rk
CROSS JOIN churn;
