"""Fee transparency calculator — total expense ratio analysis.

Computes weighted TER across client holdings and suggests
lower-cost alternatives (typically ETFs).

⚠️ Risk R-10: This module is for client-facing app only,
NOT the advisor commission tool.

Reference data: data/fund_fees.json (static, updated manually).
"""

import json
import logging
import sqlite3
from pathlib import Path
from typing import List, Optional

from interfaces import FeeReport, FundFee, Alternative

logger = logging.getLogger(__name__)

FEES_JSON_PATH = Path(__file__).resolve().parent.parent / "data" / "fund_fees.json"


def _load_fee_data(fees_path: Path = FEES_JSON_PATH) -> dict:
    """Load the static fund fees reference table."""
    with open(fees_path, encoding="utf-8") as f:
        return json.load(f)


def calculate_fees(
    client_id: str,
    conn: sqlite3.Connection,
    fees_path: Path = FEES_JSON_PATH,
) -> FeeReport:
    """Calculate fee transparency report for a client.

    Args:
        client_id: Client ID to look up holdings for.
        conn: SQLite connection (must have client_portfolios table).
        fees_path: Path to fund_fees.json reference data.

    Returns:
        FeeReport with weighted TER, annual fees, and alternatives.

    Raises:
        ValueError: If client has no holdings.
    """
    fee_data = _load_fee_data(fees_path)
    funds_ref = fee_data["funds"]
    alternatives_ref = fee_data["alternatives"]

    # Fetch client holdings
    holdings = _get_client_holdings(conn, client_id)
    if not holdings:
        raise ValueError(f"No holdings found for client {client_id}")

    # Calculate per-fund fees
    fund_fees: List[FundFee] = []
    total_market_value = 0.0
    total_annual_fee = 0.0

    for h in holdings:
        fund_code = h["fund_code"]
        market_value = h["cost_basis"]

        # Look up TER from reference table
        ref = funds_ref.get(fund_code)
        if ref is None:
            logger.warning("Fund %s: no TER data — skipping fee calculation", fund_code)
            continue

        ter = ref["ter"]
        annual_fee = market_value * ter

        fund_fees.append(FundFee(
            fund_code=fund_code,
            fund_name=ref["name"],
            ter=ter,
            market_value=market_value,
            annual_fee=annual_fee,
        ))

        total_market_value += market_value
        total_annual_fee += annual_fee

    if not fund_fees:
        raise ValueError(
            f"Client {client_id} has holdings but none have TER data in reference table"
        )

    # Weighted TER
    weighted_ter = total_annual_fee / total_market_value if total_market_value > 0 else 0.0

    # Suggest alternatives for high-fee funds
    alternatives = _suggest_alternatives(fund_fees, alternatives_ref)

    return FeeReport(
        client_id=client_id,
        total_market_value=total_market_value,
        weighted_ter=weighted_ter,
        total_annual_fee=total_annual_fee,
        fund_fees=fund_fees,
        alternatives=alternatives,
    )


def calculate_fees_from_holdings(
    client_id: str,
    holdings: List[dict],
    fees_path: Path = FEES_JSON_PATH,
) -> FeeReport:
    """Calculate fees from a list of holding dicts (no DB required).

    Args:
        client_id: Client identifier.
        holdings: List of dicts with keys: fund_code, cost_basis.
        fees_path: Path to fund_fees.json reference data.

    Returns:
        FeeReport.
    """
    fee_data = _load_fee_data(fees_path)
    funds_ref = fee_data["funds"]
    alternatives_ref = fee_data["alternatives"]

    fund_fees: List[FundFee] = []
    total_market_value = 0.0
    total_annual_fee = 0.0

    for h in holdings:
        fund_code = h["fund_code"]
        market_value = h.get("cost_basis", h.get("market_value", 0.0))

        ref = funds_ref.get(fund_code)
        if ref is None:
            logger.warning("Fund %s: no TER data — skipping", fund_code)
            continue

        ter = ref["ter"]
        annual_fee = market_value * ter

        fund_fees.append(FundFee(
            fund_code=fund_code,
            fund_name=ref["name"],
            ter=ter,
            market_value=market_value,
            annual_fee=annual_fee,
        ))

        total_market_value += market_value
        total_annual_fee += annual_fee

    if not fund_fees:
        raise ValueError("No holdings have TER data in reference table")

    weighted_ter = total_annual_fee / total_market_value if total_market_value > 0 else 0.0

    alternatives = _suggest_alternatives(fund_fees, alternatives_ref)

    return FeeReport(
        client_id=client_id,
        total_market_value=total_market_value,
        weighted_ter=weighted_ter,
        total_annual_fee=total_annual_fee,
        fund_fees=fund_fees,
        alternatives=alternatives,
    )


def _get_client_holdings(
    conn: sqlite3.Connection, client_id: str
) -> List[dict]:
    """Fetch client holdings from DB."""
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT fund_code, shares, cost_basis, bank_name "
        "FROM client_portfolios WHERE client_id = ?",
        (client_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def _suggest_alternatives(
    fund_fees: List[FundFee],
    alternatives_ref: List[dict],
) -> List[Alternative]:
    """Suggest low-cost alternatives for mutual fund holdings."""
    suggestions: List[Alternative] = []
    seen: set = set()

    for ff in fund_fees:
        # Only suggest alternatives for high-fee funds (TER > 1%)
        if ff.ter <= 0.01:
            continue

        for alt in alternatives_ref:
            key = (ff.fund_code, alt["suggested_fund"])
            if key in seen:
                continue
            seen.add(key)

            ter_savings = ff.ter - alt["suggested_ter"]
            if ter_savings <= 0:
                continue

            annual_savings = ff.market_value * ter_savings

            suggestions.append(Alternative(
                current_fund=ff.fund_code,
                suggested_fund=alt["suggested_fund"],
                suggested_name=alt["suggested_name"],
                current_ter=ff.ter,
                suggested_ter=alt["suggested_ter"],
                ter_savings=ter_savings,
                annual_savings=annual_savings,
                category=alt.get("category", ""),
            ))

    # Sort by annual savings descending
    suggestions.sort(key=lambda a: a.annual_savings, reverse=True)
    return suggestions
