"""Crisis response engine — triggers on market drops >3%, generates reassurance.

Flow:
  1. Check if market (MI_INDEX composite) dropped >3% today
  2. Identify which sectors dropped most
  3. Scan all client portfolios for exposure to dropped sectors
  4. Calculate estimated loss per client
  5. Generate historical comparisons (hardcoded past crashes)
  6. Generate per-client reassurance talking points via Claude API

Used by: manual trigger, or called from anomaly detector pipeline.
"""

import logging
import sqlite3
from datetime import date, datetime
from typing import List, Optional

from interfaces import CrisisClient, CrisisReport

logger = logging.getLogger(__name__)

# Crisis trigger threshold (absolute value)
CRISIS_THRESHOLD = 0.03  # 3%

# Historical Taiwan market crashes for comparison
HISTORICAL_CRASHES = [
    {
        "event": "2008 金融海嘯",
        "date": "2008-09-15",
        "drop": "-46%",
        "recovery_months": "14",
        "description": "雷曼倒閉引發全球金融危機，台股從 9,309 跌至 3,955，"
                        "但 14 個月後回到跌前水準。",
    },
    {
        "event": "2020 COVID-19 崩盤",
        "date": "2020-03-19",
        "drop": "-28%",
        "recovery_months": "5",
        "description": "疫情恐慌導致全球股災，台股從 12,197 跌至 8,681，"
                        "但 5 個月後完全收復，並在年底創新高。",
    },
    {
        "event": "2022 升息循環",
        "date": "2022-10-25",
        "drop": "-31%",
        "recovery_months": "10",
        "description": "聯準會激進升息，台股從 18,619 跌至 12,629，"
                        "約 10 個月後回到前高水準。",
    },
]


def check_crisis_trigger(
    conn: Optional[sqlite3.Connection] = None,
    market_data: Optional[List[dict]] = None,
    threshold: float = CRISIS_THRESHOLD,
) -> tuple[bool, float, List[dict]]:
    """Check if market dropped enough to trigger crisis response.

    Args:
        conn: SQLite connection for fetching cached benchmark data.
        market_data: Pre-fetched MI_INDEX data (list of dicts with
            industry, return_rate). If None, fetches from DB or API.
        threshold: Drop threshold as positive decimal (default 0.03).

    Returns:
        Tuple of (is_crisis, market_drop_pct, dropped_sectors).
        market_drop_pct is negative when market fell.
        dropped_sectors: list of dicts with industry, return_rate.
    """
    indices = market_data if market_data is not None else _fetch_market_data(conn)

    if not indices:
        logger.warning("No market data available for crisis check")
        return False, 0.0, []

    # Calculate overall market change (equal-weighted avg of industry returns)
    returns = [
        idx.get("return_rate", 0) for idx in indices
        if idx.get("return_rate") is not None
    ]
    if not returns:
        return False, 0.0, []

    avg_return = sum(returns) / len(returns)

    # Identify sectors that dropped
    dropped = [
        idx for idx in indices
        if (idx.get("return_rate") or 0) < 0
    ]
    dropped.sort(key=lambda x: x.get("return_rate", 0))

    is_crisis = avg_return < -threshold
    return is_crisis, avg_return, dropped


def generate_crisis_response(
    conn: sqlite3.Connection,
    market_data: Optional[List[dict]] = None,
    threshold: float = CRISIS_THRESHOLD,
    generate_ai: bool = True,
    api_key: Optional[str] = None,
) -> CrisisReport:
    """Generate full crisis response report.

    Args:
        conn: SQLite connection with clients, client_portfolios,
              fund_holdings, benchmark_index tables.
        market_data: Pre-fetched MI_INDEX data. If None, fetches from DB/API.
        threshold: Crisis trigger threshold.
        generate_ai: Whether to generate AI talking points.
        api_key: Anthropic API key (optional).

    Returns:
        CrisisReport with affected clients and reassurance data.

    Raises:
        ValueError: If no crisis detected (call check_crisis_trigger first).
    """
    is_crisis, market_drop, dropped_sectors = check_crisis_trigger(
        conn, market_data, threshold
    )

    if not is_crisis:
        raise ValueError(
            f"No crisis detected: market change {market_drop:.2%} "
            f"does not exceed -{threshold:.0%} threshold"
        )

    today = date.today().isoformat()

    # Scan all client portfolios
    affected = _scan_affected_clients(conn, dropped_sectors)

    # Generate per-client talking points
    for client in affected:
        if generate_ai:
            client.talking_point = _generate_client_talking_point(
                client, market_drop, api_key=api_key
            )
        else:
            client.talking_point = _template_talking_point(
                client, market_drop
            )

    # General talking points
    general_talking = ""
    if generate_ai:
        general_talking = _generate_general_talking_points(
            market_drop, len(affected), api_key=api_key
        )
    if not general_talking:
        general_talking = _template_general_talking_points(
            market_drop, len(affected)
        )

    return CrisisReport(
        trigger_date=today,
        market_drop_pct=market_drop,
        affected_clients=affected,
        historical_comparisons=HISTORICAL_CRASHES,
        talking_points=general_talking,
    )


def _fetch_market_data(conn: Optional[sqlite3.Connection]) -> List[dict]:
    """Fetch MI_INDEX data from DB cache or TWSE API."""
    if conn is not None:
        try:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT industry, return_rate FROM benchmark_index "
                "WHERE index_name = 'MI_INDEX' AND period = 'latest'"
            ).fetchall()
            if rows:
                return [
                    {"industry": r["industry"], "return_rate": r["return_rate"]}
                    for r in rows
                ]
        except Exception as e:
            logger.warning("DB fetch failed: %s", e)

    # Fallback: try TWSE API
    try:
        from data.twse_client import get_industry_indices
        return get_industry_indices(conn=conn)
    except Exception as e:
        logger.warning("TWSE API fetch failed: %s", e)
        return []


def _scan_affected_clients(
    conn: sqlite3.Connection,
    dropped_sectors: List[dict],
) -> List[CrisisClient]:
    """Scan all clients for exposure to dropped sectors."""
    conn.row_factory = sqlite3.Row

    dropped_industries = {
        s["industry"]: s.get("return_rate", 0) for s in dropped_sectors
    }

    clients = conn.execute("SELECT client_id, name FROM clients").fetchall()
    affected = []

    for client in clients:
        cid = client["client_id"]
        name = client["name"]

        # Get portfolio value
        portfolio = conn.execute(
            "SELECT fund_code, cost_basis FROM client_portfolios "
            "WHERE client_id = ?",
            (cid,),
        ).fetchall()

        if not portfolio:
            continue

        total_value = sum(r["cost_basis"] for r in portfolio)
        if total_value == 0:
            continue

        # Calculate exposure to dropped sectors
        exposure_value = 0.0
        estimated_loss = 0.0

        for holding in portfolio:
            fund_weight = holding["cost_basis"] / total_value
            fund_value = holding["cost_basis"]

            # Get fund's sector breakdown
            sectors = conn.execute(
                "SELECT industry, weight, return_rate FROM fund_holdings "
                "WHERE fund_code = ? AND period = 'latest'",
                (holding["fund_code"],),
            ).fetchall()

            for sector in sectors:
                ind = sector["industry"]
                if ind in dropped_industries:
                    sector_exposure = fund_weight * sector["weight"]
                    exposure_value += sector_exposure
                    # Estimated loss = exposure * sector drop
                    sector_drop = dropped_industries[ind]
                    estimated_loss += fund_value * sector["weight"] * abs(sector_drop)

        exposure_pct = exposure_value
        if exposure_pct > 0:
            affected.append(CrisisClient(
                client_id=cid,
                name=name,
                exposure_pct=exposure_pct,
                estimated_loss=estimated_loss,
                talking_point="",
            ))

    # Sort by exposure (most exposed first)
    affected.sort(key=lambda c: c.exposure_pct, reverse=True)
    return affected


def _fmt_pct(value: float) -> str:
    return f"{value * 100:.2f}%"


def _fmt_twd(value: float) -> str:
    return f"NT${value:,.0f}"


def _template_talking_point(client: CrisisClient, market_drop: float) -> str:
    """Fallback per-client reassurance template."""
    return (
        f"{client.name}您好，今日市場波動較大（{_fmt_pct(market_drop)}），"
        f"您的投資組合約有 {_fmt_pct(client.exposure_pct)} 暴露於下跌產業，"
        f"預估影響約 {_fmt_twd(client.estimated_loss)}。"
        f"歷史經驗顯示，台股在重大修正後均能收復失地。"
        f"建議維持紀律，避免恐慌賣出。"
    )


def _template_general_talking_points(
    market_drop: float, affected_count: int
) -> str:
    """Fallback general reassurance template."""
    return (
        f"今日台股大盤下跌 {_fmt_pct(abs(market_drop))}，"
        f"共 {affected_count} 位客戶受影響。\n\n"
        "歷史參考：\n"
        "- 2008 金融海嘯：跌 46%，14 個月收復\n"
        "- 2020 COVID-19：跌 28%，5 個月收復\n"
        "- 2022 升息循環：跌 31%，10 個月收復\n\n"
        "建議要點：\n"
        "1. 保持冷靜，歷史顯示市場總會復甦\n"
        "2. 避免在低點恐慌賣出\n"
        "3. 分批加碼優質標的\n"
        "4. 確認投資期限與風險承受度"
    )


def _generate_client_talking_point(
    client: CrisisClient,
    market_drop: float,
    api_key: Optional[str] = None,
) -> str:
    """Generate personalized reassurance via Claude API."""
    try:
        import anthropic
        from config.settings import ANTHROPIC_API_KEY, AI_TIMEOUT_SECONDS

        key = api_key or ANTHROPIC_API_KEY
        if not key:
            return _template_talking_point(client, market_drop)

        prompt = (
            "你是一位經驗豐富的台灣理財顧問。"
            "市場今日大幅下跌，你需要安撫客戶。\n\n"
            f"客戶名稱：{client.name}\n"
            f"市場跌幅：{_fmt_pct(market_drop)}\n"
            f"客戶暴露比例：{_fmt_pct(client.exposure_pct)}\n"
            f"預估損失：{_fmt_twd(client.estimated_loss)}\n\n"
            "## 規則\n"
            "1. 僅使用上方提供的精確數字\n"
            "2. 語氣溫暖、專業、堅定\n"
            "3. 提及歷史復甦案例\n"
            "4. 100-150 字繁體中文\n"
            "5. 不要使用過度樂觀的語氣\n\n"
            "## 任務\n"
            "寫一段可以直接發送給客戶的安撫訊息。"
        )

        anthropic_client = anthropic.Anthropic(api_key=key)
        message = anthropic_client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=512,
            timeout=AI_TIMEOUT_SECONDS,
            messages=[{"role": "user", "content": prompt}],
        )
        return message.content[0].text

    except Exception as e:
        logger.warning("AI talking point failed for %s: %s", client.client_id, e)
        return _template_talking_point(client, market_drop)


def _generate_general_talking_points(
    market_drop: float,
    affected_count: int,
    api_key: Optional[str] = None,
) -> str:
    """Generate general reassurance talking points via Claude API."""
    try:
        import anthropic
        from config.settings import ANTHROPIC_API_KEY, AI_TIMEOUT_SECONDS

        key = api_key or ANTHROPIC_API_KEY
        if not key:
            return ""

        prompt = (
            "你是一位資深投資研究總監，正在為理財顧問團隊準備危機應對話術。\n\n"
            f"今日台股大盤跌幅：{_fmt_pct(abs(market_drop))}\n"
            f"受影響客戶數：{affected_count}\n\n"
            "歷史參考：\n"
            "- 2008 金融海嘯：跌 46%，14 個月收復\n"
            "- 2020 COVID-19：跌 28%，5 個月收復\n"
            "- 2022 升息循環：跌 31%，10 個月收復\n\n"
            "## 規則\n"
            "1. 僅使用上方提供的精確數字\n"
            "2. 200-300 字繁體中文\n"
            "3. 分為：情況摘要、歷史對比、行動建議 三段\n"
            "4. 專業但不冷漠\n\n"
            "## 任務\n"
            "寫一份顧問團隊可以立即使用的危機應對話術。"
        )

        anthropic_client = anthropic.Anthropic(api_key=key)
        message = anthropic_client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1024,
            timeout=AI_TIMEOUT_SECONDS,
            messages=[{"role": "user", "content": prompt}],
        )
        return message.content[0].text

    except Exception as e:
        logger.warning("AI general talking points failed: %s", e)
        return ""
