-- =====================================================================
-- 02_customer_rfm.sql
-- Customer segmentation, loyalty and churn analysis.
-- =====================================================================

-- Q6: Calculate RFM scores for all customers
-- Business question: Which customers are Champions, Loyal, At Risk, Lost or New?
-- Expected output: Customer-level recency, frequency, monetary value and RFM segment.
WITH metrics AS (
    SELECT
        o.customer_id,
        CAST(julianday((SELECT MAX(full_date) FROM dim_date)) - julianday(MAX(d.full_date)) AS INTEGER) AS recency_days,
        COUNT(DISTINCT o.invoice_no) AS frequency,
        ROUND(SUM(o.line_total), 2) AS monetary
    FROM fact_orders o
    JOIN dim_date d ON o.date_id = d.date_id
    GROUP BY o.customer_id
),
scored AS (
    SELECT
        m.*,
        NTILE(5) OVER (ORDER BY recency_days DESC) AS r_score,
        NTILE(5) OVER (ORDER BY frequency ASC) AS f_score,
        NTILE(5) OVER (ORDER BY monetary ASC) AS m_score
    FROM metrics m
)
SELECT
    s.customer_id,
    c.name,
    c.city_tier,
    c.loyalty_tier,
    s.recency_days,
    s.frequency,
    s.monetary,
    s.r_score,
    s.f_score,
    s.m_score,
    (s.r_score + s.f_score + s.m_score) AS rfm_total,
    CASE
        WHEN s.r_score = 5 AND s.f_score >= 4 AND s.m_score >= 4 THEN 'Champions'
        WHEN s.f_score >= 4 AND s.m_score >= 3 THEN 'Loyal'
        WHEN s.r_score = 5 AND s.f_score <= 2 THEN 'New'
        WHEN s.r_score <= 2 AND (s.f_score >= 3 OR s.m_score >= 3) THEN 'At Risk'
        WHEN s.r_score <= 2 THEN 'Lost'
        ELSE 'Average'
    END AS rfm_segment
FROM scored s
JOIN dim_customers c ON s.customer_id = c.customer_id
ORDER BY rfm_total DESC, monetary DESC;

-- Q7: Top 10% customers by revenue - Pareto contribution
-- Business question: How dependent is revenue on the highest-spending customers?
-- Expected output: Top decile customer count, revenue, total revenue and contribution percent.
WITH customer_revenue AS (
    SELECT customer_id, SUM(line_total) AS revenue
    FROM fact_orders
    GROUP BY customer_id
),
ranked AS (
    SELECT
        customer_id,
        revenue,
        NTILE(10) OVER (ORDER BY revenue DESC) AS revenue_decile
    FROM customer_revenue
)
SELECT
    COUNT(*) AS top_customer_count,
    ROUND(SUM(CASE WHEN revenue_decile = 1 THEN revenue ELSE 0 END), 2) AS top_10pct_revenue,
    ROUND(SUM(revenue), 2) AS total_revenue,
    ROUND(100.0 * SUM(CASE WHEN revenue_decile = 1 THEN revenue ELSE 0 END) / NULLIF(SUM(revenue), 0), 2) AS pct_of_total_revenue
FROM ranked;

-- Q8: Average order value by loyalty tier and city tier
-- Business question: Which customer groups generate higher basket value?
-- Expected output: AOV by loyalty/city tier plus subtotal rows.
WITH base AS (
    SELECT
        c.loyalty_tier,
        c.city_tier,
        COUNT(DISTINCT o.invoice_no) AS orders,
        ROUND(SUM(o.line_total), 2) AS revenue
    FROM fact_orders o
    JOIN dim_customers c ON o.customer_id = c.customer_id
    GROUP BY c.loyalty_tier, c.city_tier
)
SELECT loyalty_tier, city_tier, orders, revenue, ROUND(revenue / NULLIF(orders, 0), 2) AS avg_order_value, 'detail' AS row_type
FROM base
UNION ALL
SELECT loyalty_tier, 'ALL_CITY_TIERS', SUM(orders), ROUND(SUM(revenue), 2), ROUND(SUM(revenue) / NULLIF(SUM(orders), 0), 2), 'loyalty_subtotal'
FROM base
GROUP BY loyalty_tier
UNION ALL
SELECT 'ALL_LOYALTY_TIERS', city_tier, SUM(orders), ROUND(SUM(revenue), 2), ROUND(SUM(revenue) / NULLIF(SUM(orders), 0), 2), 'city_subtotal'
FROM base
GROUP BY city_tier
ORDER BY row_type, loyalty_tier, city_tier;

-- Q9: Customers who have not ordered in 90+ days
-- Business question: Which customers are at high churn risk?
-- Expected output: Customer list with last order date, days inactive and lifetime revenue.
WITH last_order AS (
    SELECT
        o.customer_id,
        MAX(d.full_date) AS last_order_date,
        CAST(julianday((SELECT MAX(full_date) FROM dim_date)) - julianday(MAX(d.full_date)) AS INTEGER) AS days_inactive,
        ROUND(SUM(o.line_total), 2) AS lifetime_revenue
    FROM fact_orders o
    JOIN dim_date d ON o.date_id = d.date_id
    GROUP BY o.customer_id
)
SELECT
    c.customer_id,
    c.name,
    c.email,
    c.city_tier,
    c.loyalty_tier,
    l.last_order_date,
    l.days_inactive,
    l.lifetime_revenue
FROM last_order l
JOIN dim_customers c ON l.customer_id = c.customer_id
WHERE l.days_inactive >= 90
ORDER BY l.lifetime_revenue DESC;

-- Q10: New vs returning customer split by month
-- Business question: Is growth coming from acquisition or repeat purchases?
-- Expected output: Monthly counts and percentages for new and returning active customers.
WITH first_purchase AS (
    SELECT customer_id, MIN(d.full_date) AS first_order_date
    FROM fact_orders o
    JOIN dim_date d ON o.date_id = d.date_id
    GROUP BY customer_id
),
monthly_activity AS (
    SELECT DISTINCT
        o.customer_id,
        d.year,
        d.month,
        printf('%04d-%02d', d.year, d.month) AS year_month
    FROM fact_orders o
    JOIN dim_date d ON o.date_id = d.date_id
)
SELECT
    ma.year_month,
    SUM(CASE WHEN strftime('%Y-%m', fp.first_order_date) = ma.year_month THEN 1 ELSE 0 END) AS new_customers,
    SUM(CASE WHEN strftime('%Y-%m', fp.first_order_date) < ma.year_month THEN 1 ELSE 0 END) AS returning_customers,
    COUNT(*) AS active_customers,
    ROUND(100.0 * SUM(CASE WHEN strftime('%Y-%m', fp.first_order_date) = ma.year_month THEN 1 ELSE 0 END) / NULLIF(COUNT(*), 0), 2) AS new_customer_pct
FROM monthly_activity ma
JOIN first_purchase fp ON ma.customer_id = fp.customer_id
GROUP BY ma.year, ma.month, ma.year_month
ORDER BY ma.year, ma.month;
