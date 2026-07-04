-- =====================================================================
-- 04_cohort_retention.sql
-- Cohort retention and lifecycle analysis.
-- =====================================================================

-- Q16: Monthly cohort retention matrix
-- Business question: Do customer cohorts keep purchasing after their first month?
-- Expected output: Cohort month with retention percent for months 0 through 6.
WITH customer_months AS (
    SELECT DISTINCT
        o.customer_id,
        date(d.full_date, 'start of month') AS order_month
    FROM fact_orders o
    JOIN dim_date d ON o.date_id = d.date_id
),
cohorts AS (
    SELECT customer_id, MIN(order_month) AS cohort_month
    FROM customer_months
    GROUP BY customer_id
),
retention AS (
    SELECT
        c.cohort_month,
        CAST((strftime('%Y', cm.order_month) - strftime('%Y', c.cohort_month)) * 12
             + (strftime('%m', cm.order_month) - strftime('%m', c.cohort_month)) AS INTEGER) AS month_number,
        COUNT(DISTINCT cm.customer_id) AS retained_customers
    FROM customer_months cm
    JOIN cohorts c ON cm.customer_id = c.customer_id
    GROUP BY c.cohort_month, month_number
),
cohort_size AS (
    SELECT cohort_month, COUNT(*) AS cohort_customers
    FROM cohorts
    GROUP BY cohort_month
)
SELECT
    r.cohort_month,
    cs.cohort_customers,
    ROUND(100.0 * SUM(CASE WHEN r.month_number = 0 THEN r.retained_customers ELSE 0 END) / cs.cohort_customers, 2) AS m0_retention_pct,
    ROUND(100.0 * SUM(CASE WHEN r.month_number = 1 THEN r.retained_customers ELSE 0 END) / cs.cohort_customers, 2) AS m1_retention_pct,
    ROUND(100.0 * SUM(CASE WHEN r.month_number = 2 THEN r.retained_customers ELSE 0 END) / cs.cohort_customers, 2) AS m2_retention_pct,
    ROUND(100.0 * SUM(CASE WHEN r.month_number = 3 THEN r.retained_customers ELSE 0 END) / cs.cohort_customers, 2) AS m3_retention_pct,
    ROUND(100.0 * SUM(CASE WHEN r.month_number = 4 THEN r.retained_customers ELSE 0 END) / cs.cohort_customers, 2) AS m4_retention_pct,
    ROUND(100.0 * SUM(CASE WHEN r.month_number = 5 THEN r.retained_customers ELSE 0 END) / cs.cohort_customers, 2) AS m5_retention_pct,
    ROUND(100.0 * SUM(CASE WHEN r.month_number = 6 THEN r.retained_customers ELSE 0 END) / cs.cohort_customers, 2) AS m6_retention_pct
FROM retention r
JOIN cohort_size cs ON r.cohort_month = cs.cohort_month
WHERE r.month_number BETWEEN 0 AND 6
GROUP BY r.cohort_month, cs.cohort_customers
ORDER BY r.cohort_month;

-- Q17: Average time between purchases per customer segment
-- Business question: How frequently do different RFM segments repurchase?
-- Expected output: RFM segment average days between orders and customer counts.
WITH orders_by_customer AS (
    SELECT DISTINCT
        o.customer_id,
        o.invoice_no,
        d.full_date AS order_date
    FROM fact_orders o
    JOIN dim_date d ON o.date_id = d.date_id
),
gaps AS (
    SELECT
        customer_id,
        julianday(order_date) - julianday(LAG(order_date) OVER (PARTITION BY customer_id ORDER BY order_date)) AS days_between_orders
    FROM orders_by_customer
),
metrics AS (
    SELECT
        o.customer_id,
        CAST(julianday((SELECT MAX(full_date) FROM dim_date)) - julianday(MAX(d.full_date)) AS INTEGER) AS recency_days,
        COUNT(DISTINCT o.invoice_no) AS frequency,
        SUM(o.line_total) AS monetary
    FROM fact_orders o
    JOIN dim_date d ON o.date_id = d.date_id
    GROUP BY o.customer_id
),
segments AS (
    SELECT
        customer_id,
        CASE
            WHEN NTILE(5) OVER (ORDER BY recency_days DESC) = 5
             AND NTILE(5) OVER (ORDER BY frequency ASC) >= 4
             AND NTILE(5) OVER (ORDER BY monetary ASC) >= 4 THEN 'Champions'
            WHEN NTILE(5) OVER (ORDER BY frequency ASC) >= 4
             AND NTILE(5) OVER (ORDER BY monetary ASC) >= 3 THEN 'Loyal'
            WHEN NTILE(5) OVER (ORDER BY recency_days DESC) <= 2 THEN 'At Risk or Lost'
            ELSE 'Average'
        END AS segment
    FROM metrics
)
SELECT
    s.segment,
    COUNT(DISTINCT s.customer_id) AS customers,
    ROUND(AVG(g.days_between_orders), 1) AS avg_days_between_purchases
FROM segments s
LEFT JOIN gaps g ON s.customer_id = g.customer_id AND g.days_between_orders IS NOT NULL
GROUP BY s.segment
ORDER BY avg_days_between_purchases;

-- Q18: Cohort average order value over time
-- Business question: Does customer value increase or decrease as cohorts mature?
-- Expected output: Cohort month, months since first purchase and AOV.
WITH orders_month AS (
    SELECT
        o.customer_id,
        o.invoice_no,
        date(d.full_date, 'start of month') AS order_month,
        SUM(o.line_total) AS order_value
    FROM fact_orders o
    JOIN dim_date d ON o.date_id = d.date_id
    GROUP BY o.customer_id, o.invoice_no, order_month
),
cohorts AS (
    SELECT customer_id, MIN(order_month) AS cohort_month
    FROM orders_month
    GROUP BY customer_id
)
SELECT
    c.cohort_month,
    CAST((strftime('%Y', om.order_month) - strftime('%Y', c.cohort_month)) * 12
         + (strftime('%m', om.order_month) - strftime('%m', c.cohort_month)) AS INTEGER) AS months_since_first_purchase,
    COUNT(DISTINCT om.invoice_no) AS orders,
    ROUND(AVG(om.order_value), 2) AS avg_order_value
FROM orders_month om
JOIN cohorts c ON om.customer_id = c.customer_id
GROUP BY c.cohort_month, months_since_first_purchase
ORDER BY c.cohort_month, months_since_first_purchase;
