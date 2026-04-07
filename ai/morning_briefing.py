"""Morning briefing generator — daily advisor digest at 8:30.

Aggregates anomaly alerts into a prioritized daily briefing:
  1. Run anomaly scan across all clients
  2. Rank and select top 3 alerts by severity
  3. For each alert: identify affected clients, generate action + talking points
  4. Store briefing in DB for dashboard display

Used by: cron job (OPS), Streamlit dashboard (FE).
"""

import json
import logging
import sqlite3
import uuid
from collections import defaultdict
from datetime import date
from typing import List, Optional

from interfaces import AnomalyAlert, BriefingItem, MorningBriefing

logger = logging.getLogger(__name__)

# Severity ranking (lower = more severe)
_SEVERITY_RANK = {"critical": 0, "warning": 1, "info": 2}

# Signal type display names (Traditional Chinese)
_SIGNAL_NAMES = {
    "pe_percentile": "本益比偏高",
    "rsi_overbought": "RSI 超買",
    "fund_outflow": "基金連續淨流出",
    "foreign_selling": "外資連續賣超",
    "concentration_spike": "持倉過度集中",
    "style_drift": "風格偏移",
}


def generate_briefing(
    conn: sqlite3.Connection,
    market_data: Optional[dict] = None,
    top_n: int = 3,
    generate_ai: bool = True,
    api_key: Optional[str] = None,
    store: bool = True,
) -> MorningBriefing:
    """Generate the daily morning briefing.

    Args:
        conn: SQLite connection with full schema.
        market_data: Optional market data for anomaly detector.
        top_n: Number of top alerts to include (default 3).
        generate_ai: Whether to generate AI talking points.
        api_key: Anthropic API key (optional).
        store: Whether to persist briefing in DB.

    Returns:
        MorningBriefing with prioritized items.
    """
    from engine.anomaly_detector import scan_all_clients

    # 1. Scan all clients for anomalies
    alerts = scan_all_clients(conn, market_data=market_data, store_alerts=True)

    if not alerts:
        briefing = MorningBriefing(
            date=date.today().isoformat(),
            items=[],
            summary="今日無異常訊號，所有客戶投資組合狀態正常。",
        )
        if store:
            _store_briefing(conn, briefing)
        return briefing

    # 2. Group alerts by signal type and rank by severity
    grouped = _group_and_rank_alerts(alerts, top_n)

    # 3. Build briefing items with client info and talking points
    items = []
    for signal_type, signal_alerts in grouped:
        client_names, client_ids = _get_client_info(conn, signal_alerts)

        if generate_ai:
            action, talking = _generate_ai_content(
                signal_type, signal_alerts, client_names, api_key=api_key
            )
        else:
            action = _template_action(signal_type, signal_alerts)
            talking = _template_talking_points(signal_type, signal_alerts, client_names)

        items.append(BriefingItem(
            signal_type=signal_type,
            severity=signal_alerts[0].severity,
            affected_clients=client_names,
            affected_client_ids=client_ids,
            suggested_action=action,
            talking_points=talking,
        ))

    # 4. Generate summary
    summary = ""
    if generate_ai:
        summary = _generate_summary(items, api_key=api_key)
    if not summary:
        summary = _template_summary(items)

    briefing = MorningBriefing(
        date=date.today().isoformat(),
        items=items,
        summary=summary,
    )

    if store:
        _store_briefing(conn, briefing)

    return briefing


def _group_and_rank_alerts(
    alerts: List[AnomalyAlert], top_n: int
) -> List[tuple[str, List[AnomalyAlert]]]:
    """Group alerts by signal type, rank by severity, return top N."""
    grouped: dict[str, List[AnomalyAlert]] = defaultdict(list)
    for alert in alerts:
        grouped[alert.signal_type].append(alert)

    # Rank groups by worst severity in each group
    ranked = sorted(
        grouped.items(),
        key=lambda kv: min(_SEVERITY_RANK.get(a.severity, 99) for a in kv[1]),
    )

    return ranked[:top_n]


def _get_client_info(
    conn: sqlite3.Connection, alerts: List[AnomalyAlert]
) -> tuple[List[str], List[str]]:
    """Get client names and IDs from alerts."""
    conn.row_factory = sqlite3.Row
    client_ids = list({a.client_id for a in alerts})
    names = []

    for cid in client_ids:
        row = conn.execute(
            "SELECT name FROM clients WHERE client_id = ?", (cid,)
        ).fetchone()
        names.append(row["name"] if row else cid)

    return names, client_ids


def _signal_name(signal_type: str) -> str:
    return _SIGNAL_NAMES.get(signal_type, signal_type)


def _template_action(
    signal_type: str, alerts: List[AnomalyAlert]
) -> str:
    """Template-based suggested action."""
    name = _signal_name(signal_type)
    count = len({a.client_id for a in alerts})
    severity = alerts[0].severity

    if severity == "critical":
        return (
            f"【緊急】{count} 位客戶觸發「{name}」警訊。"
            f"建議立即聯繫客戶，確認投資意向並評估是否需要調整。"
        )
    elif severity == "warning":
        return (
            f"【注意】{count} 位客戶出現「{name}」訊號。"
            f"建議於今日內聯繫客戶，說明市場狀況並提供建議。"
        )
    else:
        return (
            f"【參考】{count} 位客戶有「{name}」情形。"
            f"可於下次定期聯繫時提及。"
        )


def _template_talking_points(
    signal_type: str,
    alerts: List[AnomalyAlert],
    client_names: List[str],
) -> str:
    """Template-based talking points."""
    name = _signal_name(signal_type)
    clients_str = "、".join(client_names[:3])
    if len(client_names) > 3:
        clients_str += f"等 {len(client_names)} 位"

    sample = alerts[0]
    return (
        f"影響客戶：{clients_str}\n"
        f"訊號：{name}（{sample.severity}）\n"
        f"說明：{sample.message}\n\n"
        f"建議話術：「您好，我注意到您持有的部分標的近期出現{name}訊號，"
        f"這是正常的市場波動。我已經為您持續關注，"
        f"如有需要調整，我會主動跟您討論。」"
    )


def _template_summary(items: List[BriefingItem]) -> str:
    """Template-based executive summary."""
    today = date.today().isoformat()
    critical = sum(1 for i in items if i.severity == "critical")
    warning = sum(1 for i in items if i.severity == "warning")
    total_clients = len({
        cid for item in items for cid in item.affected_client_ids
    })

    lines = [f"📋 {today} 晨報摘要"]
    if critical > 0:
        lines.append(f"🔴 {critical} 項緊急警訊")
    if warning > 0:
        lines.append(f"🟡 {warning} 項注意事項")
    lines.append(f"👥 共影響 {total_clients} 位客戶")

    for i, item in enumerate(items, 1):
        lines.append(
            f"\n{i}. 【{item.severity.upper()}】{_signal_name(item.signal_type)}"
            f"（{len(item.affected_clients)} 位客戶）"
        )

    return "\n".join(lines)


def _generate_ai_content(
    signal_type: str,
    alerts: List[AnomalyAlert],
    client_names: List[str],
    api_key: Optional[str] = None,
) -> tuple[str, str]:
    """Generate action + talking points via Claude API."""
    try:
        import anthropic
        from config.settings import ANTHROPIC_API_KEY, AI_TIMEOUT_SECONDS

        key = api_key or ANTHROPIC_API_KEY
        if not key:
            return (
                _template_action(signal_type, alerts),
                _template_talking_points(signal_type, alerts, client_names),
            )

        name = _signal_name(signal_type)
        count = len(client_names)
        sample = alerts[0]

        prompt = (
            "你是一位資深投資研究總監，正在為理財顧問團隊準備晨報內容。\n\n"
            f"警訊類型：{name}\n"
            f"嚴重程度：{sample.severity}\n"
            f"影響客戶數：{count}\n"
            f"範例客戶：{'、'.join(client_names[:3])}\n"
            f"警訊說明：{sample.message}\n\n"
            "## 規則\n"
            "1. 僅使用上方提供的資訊\n"
            "2. 繁體中文，專業但溫暖\n"
            "3. 不要使用 Brinson、attribution 等專業術語\n\n"
            "## 任務\n"
            "回覆 JSON 格式：\n"
            '{"action": "建議行動（50-80字）", '
            '"talking_points": "客戶話術（100-150字，含開場白）"}'
        )

        client = anthropic.Anthropic(api_key=key)
        message = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=512,
            timeout=AI_TIMEOUT_SECONDS,
            messages=[{"role": "user", "content": prompt}],
        )

        text = message.content[0].text
        parsed = _parse_json_response(text)
        if parsed:
            return parsed.get("action", ""), parsed.get("talking_points", "")

    except Exception as e:
        logger.warning("AI content generation failed: %s", e)

    return (
        _template_action(signal_type, alerts),
        _template_talking_points(signal_type, alerts, client_names),
    )


def _generate_summary(
    items: List[BriefingItem],
    api_key: Optional[str] = None,
) -> str:
    """Generate executive summary via Claude API."""
    try:
        import anthropic
        from config.settings import ANTHROPIC_API_KEY, AI_TIMEOUT_SECONDS

        key = api_key or ANTHROPIC_API_KEY
        if not key:
            return ""

        items_text = "\n".join(
            f"- {_signal_name(i.signal_type)}（{i.severity}）：{len(i.affected_clients)} 位客戶"
            for i in items
        )

        prompt = (
            "你是一位理財顧問團隊的主管。根據以下警訊摘要，"
            "寫一段 100 字以內的晨報開場白。\n\n"
            f"今日警訊：\n{items_text}\n\n"
            "## 規則\n"
            "1. 繁體中文，簡潔有力\n"
            "2. 指出最重要的 1-2 項\n"
            "3. 結尾給出一句行動指引\n"
        )

        client = anthropic.Anthropic(api_key=key)
        message = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=256,
            timeout=AI_TIMEOUT_SECONDS,
            messages=[{"role": "user", "content": prompt}],
        )
        return message.content[0].text

    except Exception as e:
        logger.warning("AI summary generation failed: %s", e)
        return ""


def _parse_json_response(text: str) -> Optional[dict]:
    """Parse JSON from Claude response."""
    if "```json" in text:
        start = text.index("```json") + 7
        end = text.index("```", start)
        text = text[start:end].strip()
    elif "```" in text:
        start = text.index("```") + 3
        end = text.index("```", start)
        text = text[start:end].strip()

    try:
        return json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return None


def _store_briefing(conn: sqlite3.Connection, briefing: MorningBriefing) -> None:
    """Persist briefing to DB."""
    try:
        content = {
            "date": briefing.date,
            "summary": briefing.summary,
            "items": [
                {
                    "signal_type": item.signal_type,
                    "severity": item.severity,
                    "affected_clients": item.affected_clients,
                    "affected_client_ids": item.affected_client_ids,
                    "suggested_action": item.suggested_action,
                    "talking_points": item.talking_points,
                }
                for item in briefing.items
            ],
        }
        conn.execute(
            "INSERT OR REPLACE INTO briefings (briefing_id, date, content_json) "
            "VALUES (?, ?, ?)",
            (str(uuid.uuid4()), briefing.date, json.dumps(content, ensure_ascii=False)),
        )
        conn.commit()
        logger.info("Briefing stored for %s", briefing.date)
    except Exception as e:
        logger.warning("Failed to store briefing: %s", e)


def get_briefing(conn: sqlite3.Connection, target_date: str) -> Optional[dict]:
    """Retrieve a stored briefing by date."""
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT content_json, generated_at FROM briefings WHERE date = ? "
        "ORDER BY generated_at DESC LIMIT 1",
        (target_date,),
    ).fetchone()

    if row is None:
        return None

    return json.loads(row["content_json"])
