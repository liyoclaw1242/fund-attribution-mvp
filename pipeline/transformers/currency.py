"""Currency converter — convert foreign amounts to TWD using fx_rate table."""

import logging
from datetime import date

import asyncpg

logger = logging.getLogger(__name__)


async def convert(
    amount: float,
    from_currency: str,
    target_date: date | str,
    pool: asyncpg.Pool,
) -> float:
    """Convert a foreign-denominated amount to TWD.

    Args:
        amount: Amount in the source currency.
        from_currency: ISO 4217 code (e.g. "USD", "HKD").
        target_date: Date for the FX rate lookup.
        pool: asyncpg connection pool.

    Returns:
        Amount in TWD.

    Raises:
        ValueError: If no FX rate found for the pair/date.
    """
    if from_currency == "TWD":
        return amount

    pair = f"{from_currency}TWD"

    async with pool.acquire() as conn:
        # Try exact date first, then most recent rate
        row = await conn.fetchrow(
            """
            SELECT rate FROM fx_rate
            WHERE pair = $1 AND date <= $2
            ORDER BY date DESC
            LIMIT 1
            """,
            pair,
            target_date,
        )

    if row is None:
        raise ValueError(
            f"No FX rate found for {pair} on or before {target_date}"
        )

    rate = float(row["rate"])
    return amount * rate


async def get_rate(
    from_currency: str,
    target_date: date | str,
    pool: asyncpg.Pool,
) -> float:
    """Get the FX rate for a currency pair.

    Args:
        from_currency: ISO 4217 code.
        target_date: Date for lookup.
        pool: asyncpg connection pool.

    Returns:
        The exchange rate (1 from_currency = N TWD).

    Raises:
        ValueError: If no rate found.
    """
    if from_currency == "TWD":
        return 1.0

    pair = f"{from_currency}TWD"

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT rate FROM fx_rate
            WHERE pair = $1 AND date <= $2
            ORDER BY date DESC
            LIMIT 1
            """,
            pair,
            target_date,
        )

    if row is None:
        raise ValueError(f"No FX rate found for {pair} on or before {target_date}")

    return float(row["rate"])
