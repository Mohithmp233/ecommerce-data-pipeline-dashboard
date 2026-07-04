-- =====================================================================
-- 05_dark_pattern_detection.sql
-- Pricing intelligence and dark-pattern detection.
-- =====================================================================

-- Q19: Products where price increased before a sale month then dropped during sale
-- Business question: Are any products showing artificial pre-sale price inflation?
-- Expected output: Products with pre-sale average price, sale price and inflation percentage.
WITH daily_price AS (
    SELECT
        p.product_id,
        p.stock_code,
        p.description,
        d.full_date,
        d.month,
        AVG(o.unit_price) AS avg_daily_price
    FROM fact_orders o
    JOIN dim_products p ON o.product_id = p.product_id
    JOIN dim_date d ON o.date_id = d.date_id
    GROUP BY p.product_id, p.stock_code, p.description, d.full_date, d.month
),
sale_months AS (
    SELECT 1 AS sale_month UNION ALL SELECT 7 UNION ALL SELECT 11 UNION ALL SELECT 12
),
sale_prices AS (
    SELECT
        dp.product_id,
        dp.stock_code,
        dp.description,
        dp.month AS sale_month,
        AVG(dp.avg_daily_price) AS sale_avg_price
    FROM daily_price dp
    JOIN sale_months sm ON dp.month = sm.sale_month
    GROUP BY dp.product_id, dp.stock_code, dp.description, dp.month
),
pre_sale_prices AS (
    SELECT
        sp.product_id,
        sp.sale_month,
        AVG(dp.avg_daily_price) AS pre_sale_avg_price
    FROM sale_prices sp
    JOIN daily_price dp
      ON sp.product_id = dp.product_id
     AND date(dp.full_date) BETWEEN date(
            printf('2011-%02d-01', sp.sale_month),
            '-21 days'
         )
         AND date(printf('2011-%02d-01', sp.sale_month), '-1 day')
    GROUP BY sp.product_id, sp.sale_month
)
SELECT
    sp.stock_code,
    sp.description,
    sp.sale_month,
    ROUND(ps.pre_sale_avg_price, 2) AS pre_sale_avg_price,
    ROUND(sp.sale_avg_price, 2) AS sale_avg_price,
    ROUND(100.0 * (ps.pre_sale_avg_price - sp.sale_avg_price) / NULLIF(sp.sale_avg_price, 0), 2) AS pre_sale_inflation_pct
FROM sale_prices sp
JOIN pre_sale_prices ps
  ON sp.product_id = ps.product_id
 AND sp.sale_month = ps.sale_month
WHERE ps.pre_sale_avg_price >= sp.sale_avg_price * 1.14
ORDER BY pre_sale_inflation_pct DESC;

-- Q20: Price volatility score per product
-- Business question: Which products have unstable pricing that may need review?
-- Expected output: Product-level coefficient of variation using price range as a SQLite-safe proxy.
WITH price_stats AS (
    SELECT
        p.stock_code,
        p.description,
        p.category,
        AVG(o.unit_price) AS avg_price,
        MIN(o.unit_price) AS min_price,
        MAX(o.unit_price) AS max_price,
        COUNT(DISTINCT o.unit_price) AS distinct_price_points
    FROM fact_orders o
    JOIN dim_products p ON o.product_id = p.product_id
    GROUP BY p.stock_code, p.description, p.category
)
SELECT
    stock_code,
    description,
    category,
    ROUND(avg_price, 2) AS avg_price,
    ROUND(min_price, 2) AS min_price,
    ROUND(max_price, 2) AS max_price,
    distinct_price_points,
    ROUND((max_price - min_price) / NULLIF(avg_price, 0), 4) AS price_volatility_score
FROM price_stats
WHERE distinct_price_points >= 3
ORDER BY price_volatility_score DESC
LIMIT 50;

-- Q21: Products with more than 3 price changes in 30 days
-- Business question: Which products have suspiciously frequent price changes?
-- Expected output: Product windows where price changed more than three times in a rolling 30-day period.
WITH daily_price AS (
    SELECT
        p.product_id,
        p.stock_code,
        p.description,
        d.full_date,
        ROUND(AVG(o.unit_price), 2) AS avg_price
    FROM fact_orders o
    JOIN dim_products p ON o.product_id = p.product_id
    JOIN dim_date d ON o.date_id = d.date_id
    GROUP BY p.product_id, p.stock_code, p.description, d.full_date
),
changes AS (
    SELECT
        product_id,
        stock_code,
        description,
        full_date,
        avg_price,
        CASE
            WHEN avg_price <> LAG(avg_price) OVER (PARTITION BY product_id ORDER BY full_date)
            THEN 1 ELSE 0
        END AS price_changed
    FROM daily_price
),
rolling AS (
    SELECT
        c1.product_id,
        c1.stock_code,
        c1.description,
        c1.full_date AS window_start,
        date(c1.full_date, '+30 days') AS window_end,
        SUM(c2.price_changed) AS price_changes_30d
    FROM changes c1
    JOIN changes c2
      ON c1.product_id = c2.product_id
     AND c2.full_date BETWEEN c1.full_date AND date(c1.full_date, '+30 days')
    GROUP BY c1.product_id, c1.stock_code, c1.description, c1.full_date
)
SELECT *
FROM rolling
WHERE price_changes_30d > 3
ORDER BY price_changes_30d DESC, window_start
LIMIT 50;
