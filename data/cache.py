"""SQLite cache with WAL mode and TTL-based invalidation.

All tables use an `expires_at` column (ISO 8601 datetime string).
Reads automatically return None for expired entries.
Connection uses WAL mode + busy_timeout for concurrent access.
"""

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from config.settings import DB_PATH

SCHEMA_PATH = Path(__file__).resolve().parent.parent / "schema.sql"

# Default TTL: 24 hours
DEFAULT_TTL_HOURS = 24


def _utcnow() -> datetime:
    """Current UTC time as naive datetime (for SQLite compatibility)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def get_connection(db_path: str = DB_PATH) -> sqlite3.Connection:
    """Create a connection with WAL mode and busy_timeout."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def init_db(db_path: str = DB_PATH) -> None:
    """Initialize database schema from schema.sql."""
    conn = get_connection(db_path)
    schema = SCHEMA_PATH.read_text()
    conn.executescript(schema)
    conn.close()


def _expires_at(ttl_hours: int = DEFAULT_TTL_HOURS) -> str:
    """Compute expiry timestamp as ISO 8601 string."""
    return (_utcnow() + timedelta(hours=ttl_hours)).isoformat()


def _is_expired(expires_at: str) -> bool:
    """Check if an entry has expired."""
    return _utcnow() > datetime.fromisoformat(expires_at)


# ---------------------------------------------------------------------------
# fund_holdings CRUD
# ---------------------------------------------------------------------------

def get_fund_holdings(
    conn: sqlite3.Connection,
    fund_code: str,
    period: str,
) -> Optional[list[dict]]:
    """Get cached fund holdings. Returns None if expired or missing."""
    rows = conn.execute(
        "SELECT * FROM fund_holdings WHERE fund_code = ? AND period = ?",
        (fund_code, period),
    ).fetchall()

    if not rows:
        return None

    # Check expiry on first row (all rows for same fund/period share TTL)
    if _is_expired(rows[0]["expires_at"]):
        delete_fund_holdings(conn, fund_code, period)
        return None

    return [dict(r) for r in rows]


def upsert_fund_holdings(
    conn: sqlite3.Connection,
    fund_code: str,
    period: str,
    holdings: list[dict],
    ttl_hours: int = DEFAULT_TTL_HOURS,
) -> None:
    """Insert or replace fund holdings for a given fund/period."""
    expires = _expires_at(ttl_hours)
    with conn:
        conn.executemany(
            """INSERT OR REPLACE INTO fund_holdings
               (fund_code, period, industry, weight, return_rate, source, expires_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            [
                (
                    fund_code,
                    period,
                    h["industry"],
                    h["weight"],
                    h.get("return_rate"),
                    h.get("source", "sitca"),
                    expires,
                )
                for h in holdings
            ],
        )


def delete_fund_holdings(
    conn: sqlite3.Connection, fund_code: str, period: str
) -> None:
    """Delete expired or stale fund holdings."""
    with conn:
        conn.execute(
            "DELETE FROM fund_holdings WHERE fund_code = ? AND period = ?",
            (fund_code, period),
        )


# ---------------------------------------------------------------------------
# benchmark_index CRUD
# ---------------------------------------------------------------------------

def get_benchmark_index(
    conn: sqlite3.Connection,
    index_name: str,
    period: str,
) -> Optional[list[dict]]:
    """Get cached benchmark index data. Returns None if expired or missing."""
    rows = conn.execute(
        "SELECT * FROM benchmark_index WHERE index_name = ? AND period = ?",
        (index_name, period),
    ).fetchall()

    if not rows:
        return None

    if _is_expired(rows[0]["expires_at"]):
        delete_benchmark_index(conn, index_name, period)
        return None

    return [dict(r) for r in rows]


def upsert_benchmark_index(
    conn: sqlite3.Connection,
    index_name: str,
    period: str,
    data: list[dict],
    ttl_hours: int = DEFAULT_TTL_HOURS,
) -> None:
    """Insert or replace benchmark index data."""
    expires = _expires_at(ttl_hours)
    with conn:
        conn.executemany(
            """INSERT OR REPLACE INTO benchmark_index
               (index_name, period, industry, weight, return_rate, expires_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            [
                (index_name, period, d["industry"], d["weight"], d["return_rate"], expires)
                for d in data
            ],
        )


def delete_benchmark_index(
    conn: sqlite3.Connection, index_name: str, period: str
) -> None:
    """Delete expired or stale benchmark index data."""
    with conn:
        conn.execute(
            "DELETE FROM benchmark_index WHERE index_name = ? AND period = ?",
            (index_name, period),
        )


# ---------------------------------------------------------------------------
# industry_map CRUD
# ---------------------------------------------------------------------------

def get_industry_mapping(
    conn: sqlite3.Connection, source_name: str
) -> Optional[str]:
    """Get standard name for a source industry name. No TTL (static mapping)."""
    row = conn.execute(
        "SELECT standard_name FROM industry_map WHERE source_name = ?",
        (source_name,),
    ).fetchone()
    return row["standard_name"] if row else None


def upsert_industry_mapping(
    conn: sqlite3.Connection,
    source_name: str,
    standard_name: str,
    source_system: str = "sitca",
) -> None:
    """Insert or update an industry mapping."""
    with conn:
        conn.execute(
            """INSERT OR REPLACE INTO industry_map
               (source_name, standard_name, source_system, updated_at)
               VALUES (?, ?, ?, datetime('now'))""",
            (source_name, standard_name, source_system),
        )


def get_all_industry_mappings(conn: sqlite3.Connection) -> dict[str, str]:
    """Get all industry mappings as {source_name: standard_name}."""
    rows = conn.execute("SELECT source_name, standard_name FROM industry_map").fetchall()
    return {r["source_name"]: r["standard_name"] for r in rows}


# ---------------------------------------------------------------------------
# unmapped_categories CRUD
# ---------------------------------------------------------------------------

def log_unmapped_category(
    conn: sqlite3.Connection,
    raw_name: str,
    fund_code: Optional[str] = None,
    period: Optional[str] = None,
    weight: Optional[float] = None,
) -> None:
    """Log an unmapped industry category for review."""
    with conn:
        conn.execute(
            """INSERT INTO unmapped_categories (raw_name, fund_code, period, weight)
               VALUES (?, ?, ?, ?)""",
            (raw_name, fund_code, period, weight),
        )


def get_unmapped_categories(conn: sqlite3.Connection) -> list[dict]:
    """Get all unmapped categories."""
    rows = conn.execute(
        "SELECT * FROM unmapped_categories ORDER BY logged_at DESC"
    ).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# report_log CRUD
# ---------------------------------------------------------------------------

def log_report(
    conn: sqlite3.Connection,
    report_id: str,
    fund_code: str,
    period: str,
    brinson_mode: str = "BF2",
    advisor_name: Optional[str] = None,
    pdf_path: Optional[str] = None,
) -> None:
    """Log a generated report."""
    with conn:
        conn.execute(
            """INSERT OR REPLACE INTO report_log
               (report_id, fund_code, advisor_name, period, brinson_mode, pdf_path)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (report_id, fund_code, advisor_name, period, brinson_mode, pdf_path),
        )


def get_report(conn: sqlite3.Connection, report_id: str) -> Optional[dict]:
    """Get a report log entry."""
    row = conn.execute(
        "SELECT * FROM report_log WHERE report_id = ?", (report_id,)
    ).fetchone()
    return dict(row) if row else None


# ---------------------------------------------------------------------------
# Maintenance
# ---------------------------------------------------------------------------

def purge_expired(conn: sqlite3.Connection) -> int:
    """Delete all expired entries from TTL-enabled tables. Returns total deleted."""
    now = _utcnow().isoformat()
    total = 0
    with conn:
        for table in ("fund_holdings", "benchmark_index"):
            cursor = conn.execute(
                f"DELETE FROM {table} WHERE expires_at < ?", (now,)
            )
            total += cursor.rowcount
    return total
