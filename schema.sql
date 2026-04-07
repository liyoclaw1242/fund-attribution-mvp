-- Fund Attribution MVP — SQLite Schema
-- Initialize with: PRAGMA journal_mode=WAL; PRAGMA busy_timeout=5000;

PRAGMA journal_mode=WAL;
PRAGMA busy_timeout=5000;

CREATE TABLE IF NOT EXISTS fund_holdings (
    fund_code   TEXT NOT NULL,
    period      TEXT NOT NULL,
    industry    TEXT NOT NULL,
    weight      REAL NOT NULL,
    return_rate REAL,
    source      TEXT DEFAULT 'sitca',
    fetched_at  TEXT NOT NULL DEFAULT (datetime('now')),
    expires_at  TEXT NOT NULL,
    PRIMARY KEY (fund_code, period, industry)
);

CREATE TABLE IF NOT EXISTS benchmark_index (
    index_name  TEXT NOT NULL,
    period      TEXT NOT NULL,
    industry    TEXT NOT NULL,
    weight      REAL NOT NULL,
    return_rate REAL NOT NULL,
    fetched_at  TEXT NOT NULL DEFAULT (datetime('now')),
    expires_at  TEXT NOT NULL,
    PRIMARY KEY (index_name, period, industry)
);

CREATE TABLE IF NOT EXISTS industry_map (
    source_name   TEXT PRIMARY KEY,
    standard_name TEXT NOT NULL,
    source_system TEXT DEFAULT 'sitca',
    updated_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS unmapped_categories (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    raw_name  TEXT NOT NULL,
    fund_code TEXT,
    period    TEXT,
    weight    REAL,
    logged_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS report_log (
    report_id    TEXT PRIMARY KEY,
    fund_code    TEXT NOT NULL,
    advisor_name TEXT,
    period       TEXT NOT NULL,
    brinson_mode TEXT NOT NULL DEFAULT 'BF2',
    created_at   TEXT NOT NULL DEFAULT (datetime('now')),
    pdf_path     TEXT
);

-- v2.0: Multi-client portfolio tables

CREATE TABLE IF NOT EXISTS clients (
    client_id      TEXT PRIMARY KEY,
    name           TEXT NOT NULL,
    kyc_risk_level TEXT DEFAULT 'moderate',
    created_at     TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS client_portfolios (
    client_id  TEXT NOT NULL,
    fund_code  TEXT NOT NULL,
    bank_name  TEXT DEFAULT '',
    shares     REAL NOT NULL DEFAULT 0,
    cost_basis REAL NOT NULL DEFAULT 0,
    added_at   TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (client_id, fund_code, bank_name),
    FOREIGN KEY (client_id) REFERENCES clients(client_id)
);

CREATE INDEX IF NOT EXISTS idx_portfolios_client ON client_portfolios(client_id);
CREATE INDEX IF NOT EXISTS idx_portfolios_fund ON client_portfolios(fund_code);

-- v2.0: Goal tracking

CREATE TABLE IF NOT EXISTS client_goals (
    goal_id     TEXT PRIMARY KEY,
    client_id   TEXT NOT NULL,
    goal_type   TEXT NOT NULL DEFAULT 'retirement',  -- retirement, house, education
    target_amount REAL NOT NULL,
    target_year INTEGER NOT NULL,
    monthly_contribution REAL NOT NULL DEFAULT 0,
    risk_tolerance TEXT NOT NULL DEFAULT 'moderate',  -- conservative, moderate, aggressive
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at  TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (client_id) REFERENCES clients(client_id)
);

CREATE INDEX IF NOT EXISTS idx_goals_client ON client_goals(client_id);

-- v2.0: Anomaly alerts

CREATE TABLE IF NOT EXISTS anomaly_alerts (
    alert_id     TEXT PRIMARY KEY,
    client_id    TEXT NOT NULL,
    fund_code    TEXT NOT NULL,
    signal_type  TEXT NOT NULL,
    severity     TEXT NOT NULL DEFAULT 'warning',
    value        REAL,
    threshold    REAL,
    message      TEXT,
    detected_at  TEXT NOT NULL DEFAULT (datetime('now')),
    acknowledged_at TEXT,
    FOREIGN KEY (client_id) REFERENCES clients(client_id)
);

CREATE INDEX IF NOT EXISTS idx_alerts_client ON anomaly_alerts(client_id);
CREATE INDEX IF NOT EXISTS idx_alerts_signal ON anomaly_alerts(signal_type);
