"""Multi-client portfolio database — CRUD, CSV import, cross-client queries.

Reuses the same SQLite WAL connection from data/cache.py.
Tables: clients, client_portfolios (see schema.sql).
"""

import csv
import logging
import uuid
from pathlib import Path
from typing import Optional

import sqlite3

from interfaces import Client, ClientHolding

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Client CRUD
# ---------------------------------------------------------------------------

def add_client(
    conn: sqlite3.Connection,
    name: str,
    kyc_risk_level: str = "moderate",
    client_id: Optional[str] = None,
) -> Client:
    """Add a new client. Returns the created Client."""
    if client_id is None:
        client_id = str(uuid.uuid4())[:8]

    with conn:
        conn.execute(
            "INSERT INTO clients (client_id, name, kyc_risk_level) VALUES (?, ?, ?)",
            (client_id, name, kyc_risk_level),
        )

    return get_client(conn, client_id)


def get_client(conn: sqlite3.Connection, client_id: str) -> Optional[Client]:
    """Get a client by ID."""
    row = conn.execute(
        "SELECT * FROM clients WHERE client_id = ?", (client_id,)
    ).fetchone()
    if row is None:
        return None
    return Client(
        client_id=row["client_id"],
        name=row["name"],
        kyc_risk_level=row["kyc_risk_level"],
        created_at=row["created_at"],
    )


def list_clients(conn: sqlite3.Connection) -> list[Client]:
    """List all clients."""
    rows = conn.execute("SELECT * FROM clients ORDER BY created_at DESC").fetchall()
    return [
        Client(
            client_id=r["client_id"],
            name=r["name"],
            kyc_risk_level=r["kyc_risk_level"],
            created_at=r["created_at"],
        )
        for r in rows
    ]


def search_clients(conn: sqlite3.Connection, query: str) -> list[Client]:
    """Search clients by name (LIKE match)."""
    rows = conn.execute(
        "SELECT * FROM clients WHERE name LIKE ? ORDER BY name",
        (f"%{query}%",),
    ).fetchall()
    return [
        Client(
            client_id=r["client_id"],
            name=r["name"],
            kyc_risk_level=r["kyc_risk_level"],
            created_at=r["created_at"],
        )
        for r in rows
    ]


# ---------------------------------------------------------------------------
# Portfolio CRUD
# ---------------------------------------------------------------------------

def add_holding(
    conn: sqlite3.Connection,
    client_id: str,
    fund_code: str,
    bank_name: str = "",
    shares: float = 0.0,
    cost_basis: float = 0.0,
) -> None:
    """Add or update a holding for a client (upsert)."""
    with conn:
        conn.execute(
            """INSERT INTO client_portfolios (client_id, fund_code, bank_name, shares, cost_basis)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(client_id, fund_code, bank_name)
               DO UPDATE SET shares = excluded.shares, cost_basis = excluded.cost_basis""",
            (client_id, fund_code, bank_name, shares, cost_basis),
        )


def remove_holding(
    conn: sqlite3.Connection,
    client_id: str,
    fund_code: str,
    bank_name: str = "",
) -> bool:
    """Remove a holding. Returns True if a row was deleted."""
    with conn:
        cursor = conn.execute(
            "DELETE FROM client_portfolios WHERE client_id = ? AND fund_code = ? AND bank_name = ?",
            (client_id, fund_code, bank_name),
        )
    return cursor.rowcount > 0


def get_portfolio(conn: sqlite3.Connection, client_id: str) -> list[ClientHolding]:
    """Get all holdings for a client."""
    rows = conn.execute(
        "SELECT * FROM client_portfolios WHERE client_id = ? ORDER BY fund_code",
        (client_id,),
    ).fetchall()
    return [
        ClientHolding(
            client_id=r["client_id"],
            fund_code=r["fund_code"],
            bank_name=r["bank_name"],
            shares=r["shares"],
            cost_basis=r["cost_basis"],
            added_at=r["added_at"],
        )
        for r in rows
    ]


def get_all_portfolios(conn: sqlite3.Connection) -> list[ClientHolding]:
    """Get all holdings across all clients."""
    rows = conn.execute(
        "SELECT * FROM client_portfolios ORDER BY client_id, fund_code"
    ).fetchall()
    return [
        ClientHolding(
            client_id=r["client_id"],
            fund_code=r["fund_code"],
            bank_name=r["bank_name"],
            shares=r["shares"],
            cost_basis=r["cost_basis"],
            added_at=r["added_at"],
        )
        for r in rows
    ]


# ---------------------------------------------------------------------------
# Cross-client queries
# ---------------------------------------------------------------------------

def get_clients_holding(conn: sqlite3.Connection, fund_code: str) -> list[dict]:
    """Get all clients holding a specific fund, with their holding details."""
    rows = conn.execute(
        """SELECT c.client_id, c.name, c.kyc_risk_level,
                  p.fund_code, p.bank_name, p.shares, p.cost_basis
           FROM client_portfolios p
           JOIN clients c ON c.client_id = p.client_id
           WHERE p.fund_code = ?
           ORDER BY c.name""",
        (fund_code,),
    ).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# CSV Import
# ---------------------------------------------------------------------------

def import_from_csv(
    conn: sqlite3.Connection,
    file_path: str | Path,
) -> dict:
    """Import client portfolios from CSV.

    Expected columns: client_name, fund_code, bank, shares, cost_basis
    Auto-creates clients that don't exist.

    Returns:
        Dict with counts: {clients_created, holdings_upserted, rows_processed}
    """
    file_path = Path(file_path)
    if not file_path.exists():
        raise FileNotFoundError(f"CSV not found: {file_path}")

    # Build name → client_id lookup
    existing = {c.name: c.client_id for c in list_clients(conn)}
    stats = {"clients_created": 0, "holdings_upserted": 0, "rows_processed": 0}

    with open(file_path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            stats["rows_processed"] += 1

            name = row["client_name"].strip()
            fund_code = row["fund_code"].strip()
            bank = row.get("bank", "").strip()
            shares = float(row.get("shares", 0))
            cost_basis = float(row.get("cost_basis", 0))

            # Auto-create client if needed
            if name not in existing:
                client = add_client(conn, name)
                existing[name] = client.client_id
                stats["clients_created"] += 1

            client_id = existing[name]
            add_holding(conn, client_id, fund_code, bank, shares, cost_basis)
            stats["holdings_upserted"] += 1

    logger.info("CSV import: %s", stats)
    return stats
