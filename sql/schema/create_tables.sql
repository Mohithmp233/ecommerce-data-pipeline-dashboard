-- =====================================================================
-- create_tables.sql
-- =====================================================================
-- Star-schema DDL for the E-Commerce Data Warehouse.
--
-- Tables created
--   * dim_date        - one row per calendar day
--   * dim_customers   - one row per customer (from simulated API)
--   * dim_products    - one row per StockCode (from product catalog)
--   * fact_orders     - one row per (non-cancelled) order line
--   * fact_returns    - one row per cancellation / refund line
--   * etl_run_log     - one row per ETL pipeline execution
--
-- Notes on portability
-- --------------------
-- The project deploys to two engines:
--     1. PostgreSQL  (local development)
--     2. SQLite      (Streamlit Cloud deployment)
--
-- To stay portable we avoid engine-specific DDL:
--     - No SERIAL / IDENTITY columns: surrogate keys are assigned
--       in Python during load and inserted as plain INTEGERs.
--     - No schema-qualified names.
--     - Standard data types only (TEXT, INTEGER, REAL, TIMESTAMP).
-- =====================================================================

-- ---------------------------------------------------------------------
-- 1. Dimension: date
-- ---------------------------------------------------------------------
DROP TABLE IF EXISTS fact_orders;
DROP TABLE IF EXISTS fact_returns;
DROP TABLE IF EXISTS dim_products;
DROP TABLE IF EXISTS dim_customers;
DROP TABLE IF EXISTS dim_date;
DROP TABLE IF EXISTS etl_run_log;

CREATE TABLE dim_date (
    date_id        INTEGER PRIMARY KEY,        -- YYYYMMDD e.g. 20111209
    full_date      DATE      NOT NULL,
    year           INTEGER   NOT NULL,
    month          INTEGER   NOT NULL,
    quarter        INTEGER   NOT NULL,
    day_of_week    TEXT,                       -- 'Monday', 'Tuesday' ...
    week_number    INTEGER,
    is_weekend     INTEGER DEFAULT 0            -- 0/1 boolean flag
);

-- ---------------------------------------------------------------------
-- 2. Dimension: customers
-- ---------------------------------------------------------------------
CREATE TABLE dim_customers (
    customer_id     INTEGER PRIMARY KEY,
    name            TEXT,
    email           TEXT,
    phone           TEXT,
    city            TEXT,
    city_tier       TEXT,                       -- 'Tier 1' / 'Tier 2' / 'Tier 3'
    country         TEXT,
    gender          TEXT,
    join_date       DATE,
    loyalty_tier    TEXT,                       -- Bronze/Silver/Gold/Platinum
    loyalty_score   INTEGER,                    -- 1-4
    customer_age_days INTEGER,
    email_opt_in    INTEGER,
    sms_opt_in      INTEGER,
    preferred_ch    TEXT
);

-- ---------------------------------------------------------------------
-- 3. Dimension: products
-- ---------------------------------------------------------------------
CREATE TABLE dim_products (
    product_id      INTEGER PRIMARY KEY,        -- synthetic surrogate
    stock_code      TEXT UNIQUE NOT NULL,
    description     TEXT,
    category        TEXT,
    sub_category    TEXT,
    unit_price      REAL,
    cost_price      REAL,
    profit_margin   REAL,                       -- %
    supplier_id     TEXT,
    reorder_level   INTEGER,
    low_stock_flag  INTEGER DEFAULT 0
);

-- ---------------------------------------------------------------------
-- 4. Fact: orders  (non-cancelled sale lines)
-- ---------------------------------------------------------------------
CREATE TABLE fact_orders (
    order_id         INTEGER PRIMARY KEY,        -- synthetic surrogate
    invoice_no       TEXT,
    customer_id      INTEGER,
    product_id       INTEGER,
    date_id          INTEGER,
    quantity         INTEGER,
    unit_price       REAL,
    line_total       REAL,
    is_cancelled     INTEGER DEFAULT 0,
    data_quality_score INTEGER,
    extraction_timestamp TIMESTAMP,
    FOREIGN KEY (customer_id) REFERENCES dim_customers(customer_id),
    FOREIGN KEY (product_id)  REFERENCES dim_products(product_id),
    FOREIGN KEY (date_id)     REFERENCES dim_date(date_id)
);

-- Index to support the most common analytical filters / joins
CREATE INDEX idx_fact_orders_customer  ON fact_orders(customer_id);
CREATE INDEX idx_fact_orders_product   ON fact_orders(product_id);
CREATE INDEX idx_fact_orders_date      ON fact_orders(date_id);
CREATE INDEX idx_fact_orders_invoice   ON fact_orders(invoice_no);

-- ---------------------------------------------------------------------
-- 5. Fact: returns  (cancellations + negative-quantity lines)
-- ---------------------------------------------------------------------
CREATE TABLE fact_returns (
    return_id        INTEGER PRIMARY KEY,
    original_invoice TEXT,
    customer_id      INTEGER,
    stock_code       TEXT,
    quantity         INTEGER,
    unit_price       REAL,
    return_date      TIMESTAMP,
    reason_code      TEXT,                       -- CANCELLATION | NEGATIVE_QTY
    country          TEXT,
    FOREIGN KEY (customer_id) REFERENCES dim_customers(customer_id)
);

CREATE INDEX idx_fact_returns_customer ON fact_returns(customer_id);
CREATE INDEX idx_fact_returns_date     ON fact_returns(return_date);

-- ---------------------------------------------------------------------
-- 6. ETL run log  (populated by etl/logger.py)
-- ---------------------------------------------------------------------
-- Note: run_id is supplied explicitly by the loader (MAX(run_id)+1) so
-- the same DDL works on both SQLite and PostgreSQL without engine-
-- specific SERIAL / AUTOINCREMENT syntax.
CREATE TABLE etl_run_log (
    run_id            INTEGER PRIMARY KEY,
    run_timestamp     TIMESTAMP NOT NULL,
    stage             TEXT,
    rows_extracted    INTEGER,
    rows_loaded       INTEGER,
    rows_rejected     INTEGER,
    status            TEXT,
    duration_seconds  REAL,
    notes             TEXT
);
