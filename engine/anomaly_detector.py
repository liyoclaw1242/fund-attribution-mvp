"""Anomaly detection engine — 6 warning signals for proactive advisor outreach.

Scans all client portfolios for:
  1. PE Percentile — fund PE above N-th percentile
  2. RSI Overbought — RSI > threshold
  3. Net Fund Outflow — negative flow for N consecutive days
  4. Foreign Investor Selling — consecutive foreign net sell days
  5. Concentration Spike — single holding > threshold of portfolio
  6. Style Drift — sector allocation deviation from baseline > threshold

Signals #1-#4: stub data sources (external market data not yet available).
Signals #5-#6: fully computed from local portfolio + attribution data.

Used by: F-203 (Morning Briefing), F-206 (Crisis Response).
"""

import logging
import sqlite3
import uuid
from typing import List, Optional, Callable

from interfaces import AnomalyAlert, AnomalyConfig

logger = logging.getLogger(__name__)


def _default_config() -> AnomalyConfig:
    """Load default config from settings, falling back to AnomalyConfig defaults."""
    try:
        from config.settings import (
            ANOMALY_PE_PERCENTILE, ANOMALY_RSI_OVERBOUGHT,
            ANOMALY_OUTFLOW_DAYS, ANOMALY_FOREIGN_SELL_DAYS,
            ANOMALY_CONCENTRATION, ANOMALY_STYLE_DRIFT,
        )
        return AnomalyConfig(
            pe_percentile=ANOMALY_PE_PERCENTILE,
            rsi_overbought=ANOMALY_RSI_OVERBOUGHT,
            outflow_consecutive_days=ANOMALY_OUTFLOW_DAYS,
            foreign_sell_consecutive_days=ANOMALY_FOREIGN_SELL_DAYS,
            concentration_threshold=ANOMALY_CONCENTRATION,
            style_drift_threshold=ANOMALY_STYLE_DRIFT,
        )
    except ImportError:
        return AnomalyConfig()


def scan_all_clients(
    conn: sqlite3.Connection,
    config: Optional[AnomalyConfig] = None,
    market_data: Optional[dict] = None,
    store_alerts: bool = True,
) -> List[AnomalyAlert]:
    """Scan all client portfolios for anomaly signals.

    Args:
        conn: SQLite connection with clients, client_portfolios,
              fund_holdings tables.
        config: Threshold configuration. Uses defaults if None.
        market_data: Optional dict with external market data for
              signals #1-#4. Keys: pe_data, rsi_data, flow_data,
              foreign_data. Each maps fund_code → value.
        store_alerts: Whether to persist alerts in anomaly_alerts table.

    Returns:
        List of all AnomalyAlert objects across all clients.
    """
    if config is None:
        config = _default_config()

    if market_data is None:
        market_data = {}

    clients = _get_all_clients(conn)
    all_alerts: List[AnomalyAlert] = []

    for client in clients:
        client_id = client["client_id"]
        holdings = _get_holdings(conn, client_id)
        if not holdings:
            continue

        alerts = scan_client(
            client_id=client_id,
            holdings=holdings,
            conn=conn,
            config=config,
            market_data=market_data,
        )

        if store_alerts and alerts:
            _store_alerts(conn, alerts)

        all_alerts.extend(alerts)

    logger.info(
        "Anomaly scan complete: %d clients, %d alerts",
        len(clients), len(all_alerts),
    )
    return all_alerts


def scan_client(
    client_id: str,
    holdings: List[dict],
    conn: Optional[sqlite3.Connection] = None,
    config: Optional[AnomalyConfig] = None,
    market_data: Optional[dict] = None,
) -> List[AnomalyAlert]:
    """Scan a single client's portfolio for all 6 signals.

    Args:
        client_id: Client ID.
        holdings: List of dicts with fund_code, cost_basis.
        conn: SQLite connection (needed for style drift baseline).
        config: Threshold config.
        market_data: External market data dict.

    Returns:
        List of AnomalyAlert for this client.
    """
    if config is None:
        config = _default_config()
    if market_data is None:
        market_data = {}

    total_value = sum(h.get("cost_basis", 0) for h in holdings)
    if total_value <= 0:
        return []

    alerts: List[AnomalyAlert] = []

    # Signal 1: PE Percentile (stub data)
    alerts.extend(_check_pe_percentile(
        client_id, holdings, config, market_data.get("pe_data", {}),
    ))

    # Signal 2: RSI Overbought (stub data)
    alerts.extend(_check_rsi_overbought(
        client_id, holdings, config, market_data.get("rsi_data", {}),
    ))

    # Signal 3: Net Fund Outflow (stub data)
    alerts.extend(_check_fund_outflow(
        client_id, holdings, config, market_data.get("flow_data", {}),
    ))

    # Signal 4: Foreign Investor Selling (stub data)
    alerts.extend(_check_foreign_selling(
        client_id, holdings, config, market_data.get("foreign_data", {}),
    ))

    # Signal 5: Concentration Spike (local data)
    alerts.extend(_check_concentration(
        client_id, holdings, total_value, config,
    ))

    # Signal 6: Style Drift (local data)
    alerts.extend(_check_style_drift(
        client_id, holdings, conn, config,
    ))

    return alerts


# ---------------------------------------------------------------------------
# Signal 1: PE Percentile
# ---------------------------------------------------------------------------

def _check_pe_percentile(
    client_id: str,
    holdings: List[dict],
    config: AnomalyConfig,
    pe_data: dict,
) -> List[AnomalyAlert]:
    """Check if any fund's PE ratio exceeds the N-th percentile.

    TODO: integrate real PE data source (e.g., TWSE, Bloomberg)
    """
    alerts = []
    for h in holdings:
        code = h["fund_code"]
        pe_percentile = pe_data.get(code)
        if pe_percentile is not None and pe_percentile > config.pe_percentile:
            alerts.append(AnomalyAlert(
                client_id=client_id,
                fund_code=code,
                signal_type="pe_percentile",
                severity="warning" if pe_percentile < 95 else "critical",
                value=pe_percentile,
                threshold=config.pe_percentile,
                message=f"{code} 本益比位於歷史 {pe_percentile:.0f} 百分位，估值偏高，留意回調風險。",
            ))
    return alerts


# ---------------------------------------------------------------------------
# Signal 2: RSI Overbought
# ---------------------------------------------------------------------------

def _check_rsi_overbought(
    client_id: str,
    holdings: List[dict],
    config: AnomalyConfig,
    rsi_data: dict,
) -> List[AnomalyAlert]:
    """Check if any fund's RSI exceeds overbought threshold.

    TODO: integrate real RSI data source
    """
    alerts = []
    for h in holdings:
        code = h["fund_code"]
        rsi = rsi_data.get(code)
        if rsi is not None and rsi > config.rsi_overbought:
            alerts.append(AnomalyAlert(
                client_id=client_id,
                fund_code=code,
                signal_type="rsi_overbought",
                severity="warning" if rsi < 80 else "critical",
                value=rsi,
                threshold=config.rsi_overbought,
                message=f"{code} RSI 達 {rsi:.1f}，進入超買區間，短期可能面臨賣壓。",
            ))
    return alerts


# ---------------------------------------------------------------------------
# Signal 3: Net Fund Outflow
# ---------------------------------------------------------------------------

def _check_fund_outflow(
    client_id: str,
    holdings: List[dict],
    config: AnomalyConfig,
    flow_data: dict,
) -> List[AnomalyAlert]:
    """Check if any fund has consecutive net outflow days.

    TODO: integrate real fund flow data source

    flow_data format: {fund_code: consecutive_outflow_days}
    """
    alerts = []
    for h in holdings:
        code = h["fund_code"]
        outflow_days = flow_data.get(code)
        if outflow_days is not None and outflow_days >= config.outflow_consecutive_days:
            alerts.append(AnomalyAlert(
                client_id=client_id,
                fund_code=code,
                signal_type="fund_outflow",
                severity="warning" if outflow_days < 10 else "critical",
                value=float(outflow_days),
                threshold=float(config.outflow_consecutive_days),
                message=f"{code} 連續 {outflow_days} 日淨流出，資金持續撤離，需留意流動性風險。",
            ))
    return alerts


# ---------------------------------------------------------------------------
# Signal 4: Foreign Investor Selling
# ---------------------------------------------------------------------------

def _check_foreign_selling(
    client_id: str,
    holdings: List[dict],
    config: AnomalyConfig,
    foreign_data: dict,
) -> List[AnomalyAlert]:
    """Check if any fund has consecutive foreign net sell days.

    TODO: integrate real foreign investor data (TWSE BWIBBU)

    foreign_data format: {fund_code: consecutive_sell_days}
    """
    alerts = []
    for h in holdings:
        code = h["fund_code"]
        sell_days = foreign_data.get(code)
        if sell_days is not None and sell_days >= config.foreign_sell_consecutive_days:
            alerts.append(AnomalyAlert(
                client_id=client_id,
                fund_code=code,
                signal_type="foreign_selling",
                severity="warning" if sell_days < 10 else "critical",
                value=float(sell_days),
                threshold=float(config.foreign_sell_consecutive_days),
                message=f"{code} 外資連續 {sell_days} 日賣超，留意市場信心變化。",
            ))
    return alerts


# ---------------------------------------------------------------------------
# Signal 5: Concentration Spike (local data — fully functional)
# ---------------------------------------------------------------------------

def _check_concentration(
    client_id: str,
    holdings: List[dict],
    total_value: float,
    config: AnomalyConfig,
) -> List[AnomalyAlert]:
    """Check if any single fund exceeds concentration threshold."""
    alerts = []

    # Aggregate same fund across banks
    fund_values: dict = {}
    for h in holdings:
        code = h["fund_code"]
        fund_values[code] = fund_values.get(code, 0) + h.get("cost_basis", 0)

    for code, value in fund_values.items():
        weight = value / total_value if total_value > 0 else 0
        if weight > config.concentration_threshold:
            pct = weight * 100
            thresh_pct = config.concentration_threshold * 100
            alerts.append(AnomalyAlert(
                client_id=client_id,
                fund_code=code,
                signal_type="concentration_spike",
                severity="warning" if weight < 0.60 else "critical",
                value=weight,
                threshold=config.concentration_threshold,
                message=f"{code} 佔投組 {pct:.1f}%，超過 {thresh_pct:.0f}% 集中度警戒線。",
            ))
    return alerts


# ---------------------------------------------------------------------------
# Signal 6: Style Drift (local data — fully functional)
# ---------------------------------------------------------------------------

def _check_style_drift(
    client_id: str,
    holdings: List[dict],
    conn: Optional[sqlite3.Connection],
    config: AnomalyConfig,
) -> List[AnomalyAlert]:
    """Check if sector allocation has drifted from baseline.

    Compares current fund_holdings sector weights against the
    benchmark index sector weights. Drift > threshold triggers alert.
    """
    if conn is None:
        return []

    alerts = []
    fund_codes = list(set(h["fund_code"] for h in holdings))

    for code in fund_codes:
        drift = _compute_style_drift(conn, code)
        if drift is not None and drift > config.style_drift_threshold:
            drift_pct = drift * 100
            thresh_pct = config.style_drift_threshold * 100
            alerts.append(AnomalyAlert(
                client_id=client_id,
                fund_code=code,
                signal_type="style_drift",
                severity="warning" if drift < 0.25 else "critical",
                value=drift,
                threshold=config.style_drift_threshold,
                message=(
                    f"{code} 產業配置偏移基準 {drift_pct:.1f}%，"
                    f"超過 {thresh_pct:.0f}% 風格漂移門檻，建議檢視持倉變動。"
                ),
            ))
    return alerts


def _compute_style_drift(
    conn: sqlite3.Connection, fund_code: str
) -> Optional[float]:
    """Compute total absolute sector weight deviation from benchmark.

    Returns sum of |Wp - Wb| / 2 across all sectors.
    A value of 0 = identical allocation, 1 = completely different.
    """
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT industry, weight FROM fund_holdings WHERE fund_code = ?",
        (fund_code,),
    ).fetchall()

    if not rows:
        return None

    fund_sectors = {r["industry"]: r["weight"] for r in rows}

    bench_rows = conn.execute(
        "SELECT industry, weight FROM benchmark_index "
        "WHERE index_name = 'MI_INDEX'",
    ).fetchall()

    if not bench_rows:
        return None

    bench_sectors = {r["industry"]: r["weight"] for r in bench_rows}

    all_sectors = set(fund_sectors.keys()) | set(bench_sectors.keys())
    total_deviation = sum(
        abs(fund_sectors.get(s, 0) - bench_sectors.get(s, 0))
        for s in all_sectors
    )

    # Normalize: max possible deviation is 2.0 (completely disjoint)
    return total_deviation / 2.0


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def _get_all_clients(conn: sqlite3.Connection) -> List[dict]:
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT client_id, name FROM clients").fetchall()
    return [dict(r) for r in rows]


def _get_holdings(conn: sqlite3.Connection, client_id: str) -> List[dict]:
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT fund_code, cost_basis, bank_name FROM client_portfolios "
        "WHERE client_id = ?",
        (client_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def _store_alerts(conn: sqlite3.Connection, alerts: List[AnomalyAlert]) -> None:
    """Persist alerts to anomaly_alerts table."""
    with conn:
        conn.executemany(
            """INSERT INTO anomaly_alerts
               (alert_id, client_id, fund_code, signal_type, severity,
                value, threshold, message)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                (
                    str(uuid.uuid4())[:8],
                    a.client_id, a.fund_code, a.signal_type,
                    a.severity, a.value, a.threshold, a.message,
                )
                for a in alerts
            ],
        )


def get_alerts_for_client(
    conn: sqlite3.Connection, client_id: str
) -> List[dict]:
    """Get all unacknowledged alerts for a client."""
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT * FROM anomaly_alerts "
        "WHERE client_id = ? AND acknowledged_at IS NULL "
        "ORDER BY detected_at DESC",
        (client_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def acknowledge_alert(conn: sqlite3.Connection, alert_id: str) -> bool:
    """Mark an alert as acknowledged."""
    with conn:
        cursor = conn.execute(
            "UPDATE anomaly_alerts SET acknowledged_at = datetime('now') "
            "WHERE alert_id = ?",
            (alert_id,),
        )
    return cursor.rowcount > 0
