-- =====================================================================
-- create_views.sql
-- =====================================================================
-- Pre-built analytical views that the Streamlit app, Excel report and
-- Tableau dashboard all consume. They encapsulate the most common
-- business questions so downstream code is a simple ``SELECT * FROM``.
--
-- Portability: these views use only ANSI-SQL window functions and
-- CTEs, so they execute unchanged on PostgreSQL and SQLite >= 3.25.
-- =====================================================================

-- ---------------------------------------------------------------------
-- v_monthly_revenue : revenue + orders + AOV + MoM growth per month
-- ---------------------------------------------------------------------
DROP VIEW IF EXISTS v_monthly_revenue;
CREATE VIEW v_monthly_revenue AS
WITH monthly AS (
    SELECT
        d.year,
        d.month,
        CAST(strftime('%Y-%m', d.full_date) AS TEXT)          AS year_month,
        COUNT(DISTINCT o.invoice_no)                          AS num_orders,
        COUNT(DISTINCT o.customer_id)                         AS active_customers,
        ROUND(SUM(o.line_total), 2)                           AS revenue
    FROM   fact_orders o
    JOIN   dim_date d ON o.date_id = d.date_id
    GROUP  BY d.year, d.month, year_month
)
SELECT
    year_month,
    year,
    month,
    revenue,
    num_orders,
    active_customers,
    ROUND(revenue / NULLIF(num_orders, 0), 2)                 AS avg_order_value,
    ROUND(
        100.0 * (revenue - LAG(revenue) OVER (ORDER BY year, month))
        / NULLIF(LAG(revenue) OVER (ORDER BY year, month), 0),
        2
    )                                                         AS mom_growth_pct,
    SUM(revenue) OVER (ORDER BY year, month)                  AS running_total_revenue
FROM   monthly
ORDER  BY year, month;

-- ---------------------------------------------------------------------
-- v_revenue_by_country : revenue + share-of-total per country
-- ---------------------------------------------------------------------
DROP VIEW IF EXISTS v_revenue_by_country;
CREATE VIEW v_revenue_by_country AS
WITH country AS (
    SELECT
        c.country,
        ROUND(SUM(o.line_total), 2)  AS revenue,
        COUNT(DISTINCT o.invoice_no) AS num_orders
    FROM  fact_orders o
    JOIN  dim_customers c ON o.customer_id = c.customer_id
    GROUP BY c.country
)
SELECT
    country,
    revenue,
    num_orders,
    ROUND(revenue / NULLIF(num_orders, 0), 2)              AS avg_order_value,
    ROUND(100.0 * revenue / NULLIF(SUM(revenue) OVER (), 0), 2) AS pct_of_total,
    RANK() OVER (ORDER BY revenue DESC)                    AS revenue_rank
FROM country
ORDER BY revenue DESC;

-- ---------------------------------------------------------------------
-- v_rfm : Recency / Frequency / Monetary + NTILE segments per customer
-- ---------------------------------------------------------------------
DROP VIEW IF EXISTS v_rfm;
CREATE VIEW v_rfm AS
WITH metrics AS (
    SELECT
        o.customer_id,
        -- Recency: days since the customer's most recent order,
        -- measured against the latest order in the dataset.
        CAST(julianday((SELECT MAX(d2.full_date) FROM dim_date d2
                        JOIN fact_orders o2 ON o2.date_id = d2.date_id))
             - julianday(MAX(d.full_date)) AS INTEGER)      AS recency,
        COUNT(DISTINCT o.invoice_no)                         AS frequency,
        ROUND(SUM(o.line_total), 2)                         AS monetary
    FROM  fact_orders o
    JOIN  dim_date d ON o.date_id = d.date_id
    GROUP BY o.customer_id
),
scored AS (
    SELECT
        customer_id, recency, frequency, monetary,
        NTILE(5) OVER (ORDER BY recency DESC)               AS r_score,   -- lower recency is better, so DESC
        NTILE(5) OVER (ORDER BY frequency ASC)              AS f_score,
        NTILE(5) OVER (ORDER BY monetary ASC)               AS m_score
    FROM metrics
)
SELECT
    s.*,
    (r_score + f_score + m_score)                           AS rfm_total,
    CASE
        WHEN r_score = 5 AND f_score >= 4 AND m_score >= 4  THEN 'Champions'
        WHEN f_score >= 4 AND m_score >= 3                  THEN 'Loyal'
        WHEN r_score = 5 AND f_score <= 2                   THEN 'New'
        WHEN r_score <= 2 AND (f_score >= 3 OR m_score >= 3) THEN 'At Risk'
        WHEN r_score <= 2                                   THEN 'Lost'
        ELSE 'Average'
    END                                                     AS segment
FROM scored s;

-- ---------------------------------------------------------------------
-- v_category_performance : revenue, margin, return rate per category
-- ---------------------------------------------------------------------
DROP VIEW IF EXISTS v_category_performance;
CREATE VIEW v_category_performance AS
SELECT
    p.category,
    ROUND(SUM(o.line_total), 2)                              AS revenue,
    ROUND(AVG(p.profit_margin), 2)                          AS avg_margin_pct,
    SUM(o.quantity)                                          AS units_sold,
    COUNT(DISTINCT o.product_id)                            AS products_sold,
    ROUND(100.0 * COUNT(DISTINCT r.return_id)
          / NULLIF(COUNT(DISTINCT o.invoice_no), 0), 2)      AS return_rate_pct
FROM       fact_orders o
JOIN       dim_products p ON o.product_id = p.product_id
LEFT JOIN  fact_returns r ON r.stock_code = p.stock_code
GROUP BY   p.category
ORDER BY   revenue DESC;

-- ---------------------------------------------------------------------
-- v_city_tier_summary : revenue, AOV, repeat rate, churn risk per tier
-- ---------------------------------------------------------------------
DROP VIEW IF EXISTS v_city_tier_summary;
CREATE VIEW v_city_tier_summary AS
WITH active AS (
    SELECT
        c.city_tier,
        COUNT(DISTINCT o.customer_id)                        AS active_customers,
        ROUND(SUM(o.line_total), 2)                         AS revenue,
        COUNT(DISTINCT o.invoice_no)                        AS num_orders
    FROM  fact_orders o
    JOIN  dim_customers c ON o.customer_id = c.customer_id
    GROUP BY c.city_tier
),
repeat AS (
    SELECT
        c.city_tier,
        COUNT(*)                                            AS repeat_customers
    FROM (
        SELECT o.customer_id, COUNT(DISTINCT o.invoice_no) AS n
        FROM fact_orders o
        JOIN dim_customers c ON o.customer_id = c.customer_id
        GROUP BY o.customer_id
        HAVING COUNT(DISTINCT o.invoice_no) > 1
    ) x
    JOIN dim_customers c ON x.customer_id = c.customer_id
    GROUP BY c.city_tier
)
SELECT
    a.city_tier,
    a.active_customers,
    a.revenue,
    a.num_orders,
    ROUND(a.revenue / NULLIF(a.num_orders, 0), 2)           AS avg_order_value,
    ROUND(100.0 * COALESCE(r.repeat_customers, 0)
          / NULLIF(a.active_customers, 0), 2)               AS repeat_rate_pct
FROM active a
LEFT JOIN repeat r ON a.city_tier = r.city_tier
ORDER BY a.revenue DESC;
