"""Portfolio + goal CRUD operations against SQLite.

Uses the existing SQLite database (cache.db) where v2.0 client tables live.
"""

import sqlite3
import uuid
from datetime import datetime
from pathlib import Path

from config.settings import DB_PATH

_DB_PATH = DB_PATH


def _get_conn() -> sqlite3.Connection:
    """Get a SQLite connection with row factory."""
    conn = sqlite3.connect(_DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


# --- Client ---

def get_client(client_id: str) -> dict | None:
    conn = _get_conn()
    try:
        row = conn.execute(
            "SELECT * FROM clients WHERE client_id = ?", (client_id,)
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def create_client(client_id: str, name: str, kyc_risk_level: str = "moderate") -> dict:
    conn = _get_conn()
    try:
        conn.execute(
            "INSERT INTO clients (client_id, name, kyc_risk_level) VALUES (?, ?, ?)",
            (client_id, name, kyc_risk_level),
        )
        conn.commit()
        return get_client(client_id)
    finally:
        conn.close()


# --- Portfolio ---

def list_portfolios() -> list[dict]:
    """List all clients with their holding counts."""
    conn = _get_conn()
    try:
        rows = conn.execute(
            """
            SELECT c.client_id, c.name, COUNT(cp.fund_code) AS holding_count
            FROM clients c
            LEFT JOIN client_portfolios cp ON c.client_id = cp.client_id
            GROUP BY c.client_id
            """
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_portfolio(client_id: str) -> list[dict]:
    """Get all holdings for a client."""
    conn = _get_conn()
    try:
        rows = conn.execute(
            "SELECT * FROM client_portfolios WHERE client_id = ? ORDER BY added_at",
            (client_id,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def create_holding(
    client_id: str, fund_code: str, bank_name: str = "",
    shares: float = 0, cost_basis: float = 0,
) -> dict:
    """Create a new holding. Upsert on (client_id, fund_code, bank_name)."""
    conn = _get_conn()
    try:
        conn.execute(
            """
            INSERT INTO client_portfolios (client_id, fund_code, bank_name, shares, cost_basis)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT (client_id, fund_code, bank_name)
            DO UPDATE SET shares = excluded.shares, cost_basis = excluded.cost_basis
            """,
            (client_id, fund_code, bank_name, shares, cost_basis),
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM client_portfolios WHERE client_id = ? AND fund_code = ? AND bank_name = ?",
            (client_id, fund_code, bank_name),
        ).fetchone()
        return dict(row)
    finally:
        conn.close()


def update_holding(
    client_id: str, fund_code: str, bank_name: str,
    shares: float | None = None, cost_basis: float | None = None,
) -> dict | None:
    """Update a holding. Returns None if not found."""
    conn = _get_conn()
    try:
        existing = conn.execute(
            "SELECT * FROM client_portfolios WHERE client_id = ? AND fund_code = ? AND bank_name = ?",
            (client_id, fund_code, bank_name),
        ).fetchone()
        if not existing:
            return None

        updates = {}
        if shares is not None:
            updates["shares"] = shares
        if cost_basis is not None:
            updates["cost_basis"] = cost_basis

        if updates:
            set_clause = ", ".join(f"{k} = ?" for k in updates)
            values = list(updates.values()) + [client_id, fund_code, bank_name]
            conn.execute(
                f"UPDATE client_portfolios SET {set_clause} WHERE client_id = ? AND fund_code = ? AND bank_name = ?",
                values,
            )
            conn.commit()

        row = conn.execute(
            "SELECT * FROM client_portfolios WHERE client_id = ? AND fund_code = ? AND bank_name = ?",
            (client_id, fund_code, bank_name),
        ).fetchone()
        return dict(row)
    finally:
        conn.close()


def delete_holding(client_id: str, fund_code: str, bank_name: str) -> bool:
    """Delete a holding. Returns True if deleted."""
    conn = _get_conn()
    try:
        cursor = conn.execute(
            "DELETE FROM client_portfolios WHERE client_id = ? AND fund_code = ? AND bank_name = ?",
            (client_id, fund_code, bank_name),
        )
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


# --- Goals ---

def list_goals(client_id: str) -> list[dict]:
    conn = _get_conn()
    try:
        rows = conn.execute(
            "SELECT * FROM client_goals WHERE client_id = ? ORDER BY created_at",
            (client_id,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_goal(goal_id: str) -> dict | None:
    conn = _get_conn()
    try:
        row = conn.execute(
            "SELECT * FROM client_goals WHERE goal_id = ?", (goal_id,)
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def create_goal(
    client_id: str, goal_type: str, target_amount: float,
    target_year: int, monthly_contribution: float = 0,
    risk_tolerance: str = "moderate",
) -> dict:
    goal_id = str(uuid.uuid4())[:8]
    now = datetime.now().isoformat()
    conn = _get_conn()
    try:
        conn.execute(
            """
            INSERT INTO client_goals
                (goal_id, client_id, goal_type, target_amount, target_year,
                 monthly_contribution, risk_tolerance, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (goal_id, client_id, goal_type, target_amount, target_year,
             monthly_contribution, risk_tolerance, now, now),
        )
        conn.commit()
        return get_goal(goal_id)
    finally:
        conn.close()


def update_goal(goal_id: str, **kwargs) -> dict | None:
    existing = get_goal(goal_id)
    if not existing:
        return None

    allowed = {"target_amount", "target_year", "monthly_contribution", "risk_tolerance"}
    updates = {k: v for k, v in kwargs.items() if k in allowed and v is not None}

    if not updates:
        return existing

    updates["updated_at"] = datetime.now().isoformat()
    set_clause = ", ".join(f"{k} = ?" for k in updates)
    values = list(updates.values()) + [goal_id]

    conn = _get_conn()
    try:
        conn.execute(
            f"UPDATE client_goals SET {set_clause} WHERE goal_id = ?", values
        )
        conn.commit()
        return get_goal(goal_id)
    finally:
        conn.close()


def delete_goal(goal_id: str) -> bool:
    conn = _get_conn()
    try:
        cursor = conn.execute(
            "DELETE FROM client_goals WHERE goal_id = ?", (goal_id,)
        )
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()
