"""Portfolio + goal CRUD operations against Postgres.

All functions are async and read/write through the async SQLAlchemy
engine owned by `service.db`. Replaces the legacy SQLite cache.db
implementation — v2.0 client tables now live in the pipeline Postgres
schema (see #129 for the port).
"""

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text

from service.db import get_engine

logger = logging.getLogger(__name__)


def _dump_datetime(value: Any) -> Any:
    """Pydantic + the test suite both expect ISO strings for timestamps."""
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def _row_to_dict(row, columns: list[str]) -> dict:
    out: dict = {}
    for col, val in zip(columns, row):
        if hasattr(val, "isoformat"):
            out[col] = val.isoformat()
        elif hasattr(val, "__float__") and not isinstance(val, (int, bool)):
            out[col] = float(val)
        else:
            out[col] = val
    return out


# --- Client ---------------------------------------------------------------


async def get_client(client_id: str) -> dict | None:
    engine = get_engine()
    if engine is None:
        logger.error("get_client called before init_engine()")
        return None
    async with engine.connect() as conn:
        row = (
            await conn.execute(
                text(
                    "SELECT client_id, name, kyc_risk_level, created_at "
                    "FROM clients WHERE client_id = :client_id"
                ),
                {"client_id": client_id},
            )
        ).first()
    if row is None:
        return None
    return _row_to_dict(row, ["client_id", "name", "kyc_risk_level", "created_at"])


async def create_client(client_id: str, name: str, kyc_risk_level: str = "moderate") -> dict:
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO clients (client_id, name, kyc_risk_level) "
                "VALUES (:client_id, :name, :kyc)"
            ),
            {"client_id": client_id, "name": name, "kyc": kyc_risk_level},
        )
    result = await get_client(client_id)
    assert result is not None
    return result


# --- Portfolio ------------------------------------------------------------


async def list_portfolios() -> list[dict]:
    """List all clients with their holding counts."""
    engine = get_engine()
    if engine is None:
        return []
    async with engine.connect() as conn:
        rows = (
            await conn.execute(
                text(
                    """
                    SELECT c.client_id, c.name, COUNT(cp.fund_code) AS holding_count
                    FROM clients c
                    LEFT JOIN client_portfolios cp ON c.client_id = cp.client_id
                    GROUP BY c.client_id, c.name
                    ORDER BY c.client_id
                    """
                )
            )
        ).all()
    return [
        {"client_id": r[0], "name": r[1], "holding_count": int(r[2] or 0)}
        for r in rows
    ]


async def get_portfolio(client_id: str) -> list[dict]:
    """Get all holdings for a client (ordered by added_at)."""
    engine = get_engine()
    if engine is None:
        return []
    async with engine.connect() as conn:
        rows = (
            await conn.execute(
                text(
                    """
                    SELECT client_id, fund_code, bank_name, shares, cost_basis, added_at
                    FROM client_portfolios
                    WHERE client_id = :client_id
                    ORDER BY added_at
                    """
                ),
                {"client_id": client_id},
            )
        ).all()
    cols = ["client_id", "fund_code", "bank_name", "shares", "cost_basis", "added_at"]
    return [_row_to_dict(r, cols) for r in rows]


async def create_holding(
    client_id: str,
    fund_code: str,
    bank_name: str = "",
    shares: float = 0,
    cost_basis: float = 0,
) -> dict:
    """Create or upsert a holding on (client_id, fund_code, bank_name)."""
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.execute(
            text(
                """
                INSERT INTO client_portfolios
                    (client_id, fund_code, bank_name, shares, cost_basis)
                VALUES
                    (:client_id, :fund_code, :bank_name, :shares, :cost_basis)
                ON CONFLICT (client_id, fund_code, bank_name)
                DO UPDATE SET
                    shares = EXCLUDED.shares,
                    cost_basis = EXCLUDED.cost_basis
                """
            ),
            {
                "client_id": client_id,
                "fund_code": fund_code,
                "bank_name": bank_name,
                "shares": shares,
                "cost_basis": cost_basis,
            },
        )

    async with engine.connect() as conn:
        row = (
            await conn.execute(
                text(
                    "SELECT client_id, fund_code, bank_name, shares, cost_basis, added_at "
                    "FROM client_portfolios "
                    "WHERE client_id = :client_id AND fund_code = :fund_code "
                    "  AND bank_name = :bank_name"
                ),
                {"client_id": client_id, "fund_code": fund_code, "bank_name": bank_name},
            )
        ).first()
    assert row is not None
    return _row_to_dict(
        row, ["client_id", "fund_code", "bank_name", "shares", "cost_basis", "added_at"]
    )


async def update_holding(
    client_id: str,
    fund_code: str,
    bank_name: str,
    shares: float | None = None,
    cost_basis: float | None = None,
) -> dict | None:
    """Update a holding. Returns None if not found."""
    engine = get_engine()
    if engine is None:
        return None

    select_sql = text(
        "SELECT client_id, fund_code, bank_name, shares, cost_basis, added_at "
        "FROM client_portfolios "
        "WHERE client_id = :client_id AND fund_code = :fund_code "
        "  AND bank_name = :bank_name"
    )
    params = {"client_id": client_id, "fund_code": fund_code, "bank_name": bank_name}

    async with engine.connect() as conn:
        existing = (await conn.execute(select_sql, params)).first()
    if existing is None:
        return None

    updates: dict[str, Any] = {}
    if shares is not None:
        updates["shares"] = shares
    if cost_basis is not None:
        updates["cost_basis"] = cost_basis

    if updates:
        set_clause = ", ".join(f"{k} = :{k}" for k in updates)
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    f"UPDATE client_portfolios SET {set_clause} "
                    f"WHERE client_id = :client_id AND fund_code = :fund_code "
                    f"  AND bank_name = :bank_name"
                ),
                {**updates, **params},
            )

    async with engine.connect() as conn:
        row = (await conn.execute(select_sql, params)).first()
    if row is None:
        return None
    return _row_to_dict(
        row, ["client_id", "fund_code", "bank_name", "shares", "cost_basis", "added_at"]
    )


async def delete_holding(client_id: str, fund_code: str, bank_name: str) -> bool:
    """Delete a holding. Returns True if a row was removed."""
    engine = get_engine()
    if engine is None:
        return False
    async with engine.begin() as conn:
        result = await conn.execute(
            text(
                "DELETE FROM client_portfolios "
                "WHERE client_id = :client_id AND fund_code = :fund_code "
                "  AND bank_name = :bank_name"
            ),
            {"client_id": client_id, "fund_code": fund_code, "bank_name": bank_name},
        )
        return bool(getattr(result, "rowcount", 0))


# --- Goals ----------------------------------------------------------------


_GOAL_COLS = [
    "goal_id",
    "client_id",
    "goal_type",
    "target_amount",
    "target_year",
    "monthly_contribution",
    "risk_tolerance",
    "created_at",
    "updated_at",
]


async def list_goals(client_id: str) -> list[dict]:
    engine = get_engine()
    if engine is None:
        return []
    async with engine.connect() as conn:
        rows = (
            await conn.execute(
                text(
                    f"SELECT {', '.join(_GOAL_COLS)} FROM client_goals "
                    f"WHERE client_id = :client_id ORDER BY created_at"
                ),
                {"client_id": client_id},
            )
        ).all()
    return [_row_to_dict(r, _GOAL_COLS) for r in rows]


async def get_goal(goal_id: str) -> dict | None:
    engine = get_engine()
    if engine is None:
        return None
    async with engine.connect() as conn:
        row = (
            await conn.execute(
                text(
                    f"SELECT {', '.join(_GOAL_COLS)} FROM client_goals "
                    f"WHERE goal_id = :goal_id"
                ),
                {"goal_id": goal_id},
            )
        ).first()
    if row is None:
        return None
    return _row_to_dict(row, _GOAL_COLS)


async def create_goal(
    client_id: str,
    goal_type: str,
    target_amount: float,
    target_year: int,
    monthly_contribution: float = 0,
    risk_tolerance: str = "moderate",
) -> dict:
    goal_id = str(uuid.uuid4())[:8]
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.execute(
            text(
                """
                INSERT INTO client_goals
                    (goal_id, client_id, goal_type, target_amount, target_year,
                     monthly_contribution, risk_tolerance)
                VALUES
                    (:goal_id, :client_id, :goal_type, :target_amount, :target_year,
                     :monthly_contribution, :risk_tolerance)
                """
            ),
            {
                "goal_id": goal_id,
                "client_id": client_id,
                "goal_type": goal_type,
                "target_amount": target_amount,
                "target_year": target_year,
                "monthly_contribution": monthly_contribution,
                "risk_tolerance": risk_tolerance,
            },
        )
    result = await get_goal(goal_id)
    assert result is not None
    return result


async def update_goal(goal_id: str, **kwargs) -> dict | None:
    existing = await get_goal(goal_id)
    if existing is None:
        return None

    allowed = {"target_amount", "target_year", "monthly_contribution", "risk_tolerance"}
    updates = {k: v for k, v in kwargs.items() if k in allowed and v is not None}
    if not updates:
        return existing

    updates["updated_at"] = datetime.now(timezone.utc)
    set_clause = ", ".join(f"{k} = :{k}" for k in updates)
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.execute(
            text(f"UPDATE client_goals SET {set_clause} WHERE goal_id = :goal_id"),
            {**updates, "goal_id": goal_id},
        )
    return await get_goal(goal_id)


async def delete_goal(goal_id: str) -> bool:
    engine = get_engine()
    if engine is None:
        return False
    async with engine.begin() as conn:
        result = await conn.execute(
            text("DELETE FROM client_goals WHERE goal_id = :goal_id"),
            {"goal_id": goal_id},
        )
        return bool(getattr(result, "rowcount", 0))
