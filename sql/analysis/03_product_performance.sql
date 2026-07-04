-- =====================================================================
-- 03_product_performance.sql
-- Product, category and inventory performance analysis.
-- =====================================================================

-- Q11: Top 20 products by revenue with profit margin
-- Business question: Which products are the biggest revenue drivers and are they profitable?
-- Expected output: Top 20 products by revenue with units, orders and margin.
SELECT
    p.stock_code,
    p.description,
    p.category,
    ROUND(SUM(o.line_total), 2) AS revenue,
    SUM(o.quantity) AS units_sold,
    COUNT(DISTINCT o.invoice_no) AS orders,
    ROUND(AVG(p.profit_margin), 2) AS avg_profit_margin_pct
FROM fact_orders o
JOIN dim_products p ON o.product_id = p.product_id
GROUP BY p.stock_code, p.description, p.category
ORDER BY revenue DESC
LIMIT 20;

-- Q12: Category-wise revenue, margin and return rate
-- Business question: Which categories perform well after accounting for returns?
-- Expected output: Category revenue, average margin, units sold and return rate.
WITH sales AS (
    SELECT
        p.category,
        ROUND(SUM(o.line_total), 2) AS revenue,
        SUM(o.quantity) AS units_sold,
        COUNT(DISTINCT o.invoice_no) AS orders,
        ROUND(AVG(p.profit_margin), 2) AS avg_margin_pct
    FROM fact_orders o
    JOIN dim_products p ON o.product_id = p.product_id
    GROUP BY p.category
),
returns AS (
    SELECT
        p.category,
        COUNT(*) AS return_lines,
        ROUND(SUM(ABS(r.quantity) * r.unit_price), 2) AS returned_value
    FROM fact_returns r
    JOIN dim_products p ON r.stock_code = p.stock_code
    GROUP BY p.category
)
SELECT
    s.category,
    s.revenue,
    s.avg_margin_pct,
    s.units_sold,
    s.orders,
    COALESCE(r.return_lines, 0) AS return_lines,
    COALESCE(r.returned_value, 0) AS returned_value,
    ROUND(100.0 * COALESCE(r.return_lines, 0) / NULLIF(s.orders, 0), 2) AS return_rate_pct
FROM sales s
LEFT JOIN returns r ON s.category = r.category
ORDER BY s.revenue DESC;

-- Q13: Products with highest return rate
-- Business question: Which products may have quality or expectation issues?
-- Expected output: Products ranked by return rate with sales and return lines.
WITH sales AS (
    SELECT p.stock_code, p.description, p.category, COUNT(*) AS sale_lines, ROUND(SUM(o.line_total), 2) AS revenue
    FROM fact_orders o
    JOIN dim_products p ON o.product_id = p.product_id
    GROUP BY p.stock_code, p.description, p.category
),
returns AS (
    SELECT stock_code, COUNT(*) AS return_lines
    FROM fact_returns
    GROUP BY stock_code
)
SELECT
    s.stock_code,
    s.description,
    s.category,
    s.sale_lines,
    COALESCE(r.return_lines, 0) AS return_lines,
    ROUND(100.0 * COALESCE(r.return_lines, 0) / NULLIF(s.sale_lines, 0), 2) AS return_rate_pct,
    s.revenue
FROM sales s
LEFT JOIN returns r ON s.stock_code = r.stock_code
WHERE s.sale_lines >= 10
ORDER BY return_rate_pct DESC, s.revenue DESC
LIMIT 25;

-- Q14: Market basket - top 10 product pairs bought together
-- Business question: Which products are frequently bought in the same invoice?
-- Expected output: Top product pairs with co-purchase counts and pair revenue.
SELECT
    p1.stock_code AS stock_code_1,
    p1.description AS product_1,
    p2.stock_code AS stock_code_2,
    p2.description AS product_2,
    COUNT(DISTINCT o1.invoice_no) AS times_bought_together,
    ROUND(SUM(o1.line_total + o2.line_total), 2) AS pair_revenue
FROM fact_orders o1
JOIN fact_orders o2
    ON o1.invoice_no = o2.invoice_no
   AND o1.product_id < o2.product_id
JOIN dim_products p1 ON o1.product_id = p1.product_id
JOIN dim_products p2 ON o2.product_id = p2.product_id
GROUP BY p1.stock_code, p1.description, p2.stock_code, p2.description
ORDER BY times_bought_together DESC, pair_revenue DESC
LIMIT 10;

-- Q15: Slow moving inventory - products ordered fewer than 5 times in last 6 months
-- Business question: Which products should merchandising review for clearance or repositioning?
-- Expected output: Low-velocity products with last-six-month order counts and stock flags.
WITH max_date AS (
    SELECT MAX(full_date) AS latest_date FROM dim_date
),
recent_sales AS (
    SELECT
        p.product_id,
        COUNT(DISTINCT o.invoice_no) AS recent_orders,
        SUM(o.quantity) AS recent_units
    FROM fact_orders o
    JOIN dim_products p ON o.product_id = p.product_id
    JOIN dim_date d ON o.date_id = d.date_id
    CROSS JOIN max_date m
    WHERE d.full_date >= date(m.latest_date, '-6 months')
    GROUP BY p.product_id
)
SELECT
    p.stock_code,
    p.description,
    p.category,
    COALESCE(rs.recent_orders, 0) AS recent_orders,
    COALESCE(rs.recent_units, 0) AS recent_units,
    p.reorder_level,
    p.low_stock_flag
FROM dim_products p
LEFT JOIN recent_sales rs ON p.product_id = rs.product_id
WHERE COALESCE(rs.recent_orders, 0) < 5
ORDER BY recent_orders ASC, p.reorder_level DESC;
