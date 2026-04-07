"""Cross-bank portfolio health check engine.

Aggregates holdings across multiple banks for a client and
detects risk issues:
  1. Concentration — single fund > 40% of total portfolio
  2. Missing asset class — lacks equity/bond/cash diversification
  3. Risk-KYC mismatch — portfolio risk vs client's kyc_risk_level

OCR statement parsing is explicitly OUT OF SCOPE (Phase 2.1).
"""

import logging
import sqlite3
from typing import List, Dict

from interfaces import HealthCheckResult, HealthIssue

logger = logging.getLogger(__name__)

# Thresholds
CONCENTRATION_THRESHOLD = 0.40  # 40% single fund

# Simple fund type classification by code prefix/pattern
# For MVP: heuristic lookup. Post-MVP: reference table.
FUND_TYPE_MAP = {
    # Taiwan ETFs → equity
    "0050": "equity", "0051": "equity", "0052": "equity",
    "0055": "equity", "0056": "equity",
    "006205": "equity", "006208": "equity",
    "00692": "equity", "00850": "equity",
    "00878": "equity", "00919": "equity",
    # Bond ETFs
    "00687B": "bond", "00679B": "bond", "00696B": "bond",
    # Money market / cash
    "CASH": "cash",
}

# Risk score: higher = more aggressive
RISK_SCORES = {
    "conservative": 1,
    "moderate": 2,
    "aggressive": 3,
}

# Asset class risk contribution
ASSET_CLASS_RISK = {
    "equity": 3,
    "bond": 1,
    "cash": 0,
    "unknown": 2,  # treat unknown as moderate
}


def check_portfolio_health(
    client_id: str,
    conn: sqlite3.Connection,
) -> HealthCheckResult:
    """Run full portfolio health check for a client.

    Args:
        client_id: Client ID.
        conn: SQLite connection with clients and client_portfolios tables.

    Returns:
        HealthCheckResult with bank breakdown and any issues found.

    Raises:
        ValueError: If client not found or has no holdings.
    """
    client = _get_client(conn, client_id)
    if client is None:
        raise ValueError(f"Client {client_id} not found")

    holdings = _get_holdings(conn, client_id)
    if not holdings:
        raise ValueError(f"No holdings found for client {client_id}")

    # Aggregate across banks
    total_value = sum(h["cost_basis"] for h in holdings)
    if total_value <= 0:
        raise ValueError(f"Client {client_id} has zero portfolio value")

    bank_breakdown = _compute_bank_breakdown(holdings)
    fund_weights = _compute_fund_weights(holdings, total_value)

    issues: List[HealthIssue] = []

    # Check 1: Concentration
    issues.extend(_check_concentration(fund_weights))

    # Check 2: Missing asset classes
    issues.extend(_check_asset_classes(fund_weights))

    # Check 3: Risk-KYC mismatch
    issues.extend(_check_kyc_mismatch(
        fund_weights, client["kyc_risk_level"]
    ))

    return HealthCheckResult(
        client_id=client_id,
        total_value=total_value,
        bank_breakdown=bank_breakdown,
        issues=issues,
    )


def check_portfolio_health_direct(
    client_id: str,
    holdings: List[dict],
    kyc_risk_level: str = "moderate",
) -> HealthCheckResult:
    """Run health check from direct holdings data (no DB).

    Args:
        client_id: Client identifier.
        holdings: List of dicts with fund_code, cost_basis, bank_name.
        kyc_risk_level: Client's KYC risk level.

    Returns:
        HealthCheckResult.
    """
    if not holdings:
        raise ValueError("No holdings provided")

    total_value = sum(h.get("cost_basis", 0) for h in holdings)
    if total_value <= 0:
        raise ValueError("Total portfolio value is zero")

    bank_breakdown = _compute_bank_breakdown(holdings)
    fund_weights = _compute_fund_weights(holdings, total_value)

    issues: List[HealthIssue] = []
    issues.extend(_check_concentration(fund_weights))
    issues.extend(_check_asset_classes(fund_weights))
    issues.extend(_check_kyc_mismatch(fund_weights, kyc_risk_level))

    return HealthCheckResult(
        client_id=client_id,
        total_value=total_value,
        bank_breakdown=bank_breakdown,
        issues=issues,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_client(conn: sqlite3.Connection, client_id: str) -> dict | None:
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT client_id, name, kyc_risk_level FROM clients WHERE client_id = ?",
        (client_id,),
    ).fetchone()
    return dict(row) if row else None


def _get_holdings(conn: sqlite3.Connection, client_id: str) -> List[dict]:
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT fund_code, bank_name, cost_basis FROM client_portfolios "
        "WHERE client_id = ?",
        (client_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def _compute_bank_breakdown(holdings: List[dict]) -> Dict[str, float]:
    """Sum holdings by bank_name."""
    breakdown: Dict[str, float] = {}
    for h in holdings:
        bank = h.get("bank_name", "") or "未指定"
        breakdown[bank] = breakdown.get(bank, 0) + h.get("cost_basis", 0)
    return breakdown


def _compute_fund_weights(
    holdings: List[dict], total_value: float
) -> Dict[str, dict]:
    """Compute per-fund weight and classify asset type."""
    funds: Dict[str, dict] = {}
    for h in holdings:
        code = h["fund_code"]
        value = h.get("cost_basis", 0)
        if code in funds:
            funds[code]["value"] += value
        else:
            funds[code] = {
                "value": value,
                "asset_class": classify_fund(code),
            }

    for code, info in funds.items():
        info["weight"] = info["value"] / total_value if total_value > 0 else 0

    return funds


def classify_fund(fund_code: str) -> str:
    """Classify a fund into an asset class.

    Simple heuristic for MVP:
    - Known codes → lookup table
    - Codes starting with '00' and ending with 'B' → bond
    - Codes starting with '00' or 4-digit numeric → equity (ETF)
    - Others → unknown (treated as moderate risk)
    """
    if fund_code in FUND_TYPE_MAP:
        return FUND_TYPE_MAP[fund_code]

    if fund_code.endswith("B"):
        return "bond"

    if fund_code.startswith("00") or (fund_code.isdigit() and len(fund_code) == 4):
        return "equity"

    return "unknown"


# ---------------------------------------------------------------------------
# Health checks
# ---------------------------------------------------------------------------

def _check_concentration(fund_weights: Dict[str, dict]) -> List[HealthIssue]:
    """Check for single-fund over-concentration (>40%)."""
    issues = []
    for code, info in fund_weights.items():
        if info["weight"] > CONCENTRATION_THRESHOLD:
            pct = info["weight"] * 100
            issues.append(HealthIssue(
                check_type="concentration",
                severity="warning",
                description=f"基金 {code} 佔投組 {pct:.1f}%，超過 40% 集中度警戒線。",
                suggestion=f"建議將 {code} 部位分散至其他基金或資產類別，降低集中風險。",
            ))
    return issues


def _check_asset_classes(fund_weights: Dict[str, dict]) -> List[HealthIssue]:
    """Check for missing asset class diversification."""
    present = set()
    for info in fund_weights.values():
        ac = info["asset_class"]
        if ac != "unknown":
            present.add(ac)

    issues = []
    expected = {"equity", "bond"}  # cash is nice-to-have but not required

    missing = expected - present
    if missing:
        missing_labels = {
            "equity": "股票型",
            "bond": "債券型",
            "cash": "現金",
        }
        missing_str = "、".join(missing_labels.get(m, m) for m in missing)
        issues.append(HealthIssue(
            check_type="asset_class",
            severity="warning",
            description=f"投資組合缺少{missing_str}資產類別，分散不足。",
            suggestion=f"建議配置部分資金至{missing_str}，提升資產配置的多元性。",
        ))

    return issues


def _check_kyc_mismatch(
    fund_weights: Dict[str, dict],
    kyc_risk_level: str,
) -> List[HealthIssue]:
    """Check if portfolio risk matches client's KYC risk level."""
    kyc_score = RISK_SCORES.get(kyc_risk_level, 2)

    # Calculate portfolio risk score (weighted average)
    total_weight = sum(info["weight"] for info in fund_weights.values())
    if total_weight == 0:
        return []

    portfolio_risk = sum(
        info["weight"] * ASSET_CLASS_RISK.get(info["asset_class"], 2)
        for info in fund_weights.values()
    ) / total_weight

    issues = []

    # Portfolio too aggressive for KYC
    if portfolio_risk > kyc_score + 0.8:
        level_labels = {
            "conservative": "保守型",
            "moderate": "穩健型",
            "aggressive": "積極型",
        }
        kyc_label = level_labels.get(kyc_risk_level, kyc_risk_level)
        issues.append(HealthIssue(
            check_type="kyc_mismatch",
            severity="critical",
            description=(
                f"投資組合風險偏高，與客戶 KYC 風險屬性「{kyc_label}」不符。"
            ),
            suggestion=(
                "建議降低股票型部位比重，增加債券或現金部位，"
                "使投組風險符合客戶風險承受度。"
            ),
        ))

    # Portfolio too conservative for KYC (informational)
    elif portfolio_risk < kyc_score - 1.2:
        issues.append(HealthIssue(
            check_type="kyc_mismatch",
            severity="warning",
            description="投資組合風險偏低，可能無法達成預期報酬目標。",
            suggestion="客戶風險承受度允許更高配置，可考慮增加股票型部位以提升報酬潛力。",
        ))

    return issues
