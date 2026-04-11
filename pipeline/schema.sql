-- Pipeline PostgreSQL schema — idempotent (CREATE TABLE IF NOT EXISTS)
-- Run on every container startup to ensure tables exist.

-- 個股基本資料（每日更新）
CREATE TABLE IF NOT EXISTS stock_info (
    stock_id    TEXT PRIMARY KEY,
    stock_name  TEXT NOT NULL,
    market      TEXT NOT NULL,            -- 'twse', 'tpex', 'us', 'hk'
    industry    TEXT,                      -- unified industry name
    industry_source TEXT,                 -- 'tse28', 'gics', 'finmind'
    shares_outstanding BIGINT,
    updated_at  TIMESTAMPTZ DEFAULT now()
);

-- 每日股價
-- Note: previously PARTITION BY LIST (substring(stock_id, 1, 1)) but Postgres
-- rejects a PRIMARY KEY on a partition key that is an expression
-- (FeatureNotSupportedError). Partition pruning by first-char was never going
-- to be efficient for TW/US mixed markets anyway, so we drop partitioning and
-- rely on a plain table + (stock_id, date) PK + date index for range scans.
CREATE TABLE IF NOT EXISTS stock_price (
    stock_id    TEXT NOT NULL,
    date        DATE NOT NULL,
    close_price NUMERIC(12,4),
    change_pct  NUMERIC(8,4),
    volume      BIGINT,
    market_cap  NUMERIC(18,0),
    source      TEXT NOT NULL,
    PRIMARY KEY (stock_id, date)
);

-- 產業指數（TWSE MI_INDEX）
CREATE TABLE IF NOT EXISTS industry_index (
    industry    TEXT NOT NULL,
    date        DATE NOT NULL,
    close_index NUMERIC(12,4),
    change_pct  NUMERIC(8,4),
    source      TEXT DEFAULT 'twse',
    PRIMARY KEY (industry, date)
);

-- 產業市值權重（每日計算）
CREATE TABLE IF NOT EXISTS industry_weight (
    industry    TEXT NOT NULL,
    date        DATE NOT NULL,
    market      TEXT NOT NULL,            -- 'twse', 'sp500', 'msci'
    weight      NUMERIC(8,6),             -- 0.000000 ~ 1.000000
    market_cap  NUMERIC(18,0),
    PRIMARY KEY (industry, date, market)
);

-- 基金資料
CREATE TABLE IF NOT EXISTS fund_info (
    fund_id     TEXT PRIMARY KEY,         -- ISIN or internal code
    fund_name   TEXT NOT NULL,
    fund_house  TEXT,
    fund_type   TEXT,                     -- 'equity', 'balanced', 'bond'
    currency    TEXT DEFAULT 'TWD',
    market      TEXT,                     -- 'tw', 'offshore', 'us'
    source      TEXT NOT NULL,            -- 'sitca', 'finnhub', 'yfinance'
    updated_at  TIMESTAMPTZ DEFAULT now()
);

-- 基金持股（Finnhub / SITCA）
CREATE TABLE IF NOT EXISTS fund_holding (
    fund_id     TEXT NOT NULL,
    as_of_date  DATE NOT NULL,
    stock_id    TEXT,
    stock_name  TEXT NOT NULL,
    weight      NUMERIC(8,6),
    asset_type  TEXT,                     -- 'equity', 'bond', 'cash', 'etf'
    sector      TEXT,
    source      TEXT NOT NULL,
    PRIMARY KEY (fund_id, as_of_date, stock_name)
);

-- 基金 NAV 歷史
CREATE TABLE IF NOT EXISTS fund_nav (
    fund_id     TEXT NOT NULL,
    date        DATE NOT NULL,
    nav         NUMERIC(12,4),
    return_1d   NUMERIC(8,6),
    source      TEXT NOT NULL,
    PRIMARY KEY (fund_id, date)
);

-- 匯率
CREATE TABLE IF NOT EXISTS fx_rate (
    pair        TEXT NOT NULL,            -- 'USDTWD'
    date        DATE NOT NULL,
    rate        NUMERIC(12,6),
    source      TEXT DEFAULT 'bot',
    PRIMARY KEY (pair, date)
);

-- Pipeline 執行紀錄
CREATE TABLE IF NOT EXISTS pipeline_run (
    id          SERIAL PRIMARY KEY,
    fetcher     TEXT NOT NULL,
    started_at  TIMESTAMPTZ NOT NULL,
    finished_at TIMESTAMPTZ,
    status      TEXT DEFAULT 'running',   -- 'success', 'failed', 'partial'
    rows_count  INT DEFAULT 0,
    error_msg   TEXT,
    params_json JSONB
);

-- Indexes for common query patterns
CREATE INDEX IF NOT EXISTS idx_stock_price_date ON stock_price (date);
CREATE INDEX IF NOT EXISTS idx_industry_index_date ON industry_index (date);
CREATE INDEX IF NOT EXISTS idx_industry_weight_date ON industry_weight (date);
CREATE INDEX IF NOT EXISTS idx_fund_holding_fund_date ON fund_holding (fund_id, as_of_date);
CREATE INDEX IF NOT EXISTS idx_fund_nav_fund_date ON fund_nav (fund_id, date);
CREATE INDEX IF NOT EXISTS idx_fx_rate_date ON fx_rate (date);
CREATE INDEX IF NOT EXISTS idx_pipeline_run_fetcher ON pipeline_run (fetcher, started_at);
