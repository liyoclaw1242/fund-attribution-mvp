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
