"""Weekly LINE message draft generator.

Produces personalized <200-char Traditional Chinese messages
for each client based on their portfolio holdings and recent
attribution results. Advisors review and send manually.

Schedule (Monday 8:00) is an OPS concern — this module is
the generator only. LINE API integration is out of scope.
"""

import logging
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import List, Optional

from interfaces import LineDraft

logger = logging.getLogger(__name__)


def generate_weekly_drafts(
    conn: sqlite3.Connection,
    week: Optional[str] = None,
    api_key: Optional[str] = None,
) -> List[LineDraft]:
    """Generate weekly LINE drafts for all clients.

    Args:
        conn: SQLite connection with clients, client_portfolios,
              fund_holdings, and line_drafts tables.
        week: ISO week string (e.g. "2026-W15"). Auto-computed if None.
        api_key: Anthropic API key (optional, uses env default).

    Returns:
        List of LineDraft objects, one per client.
    """
    if week is None:
        now = datetime.now(timezone.utc)
        week = f"{now.year}-W{now.isocalendar()[1]:02d}"

    clients = _get_all_clients(conn)
    if not clients:
        logger.info("No clients found — no drafts to generate")
        return []

    drafts: List[LineDraft] = []

    for client in clients:
        client_id = client["client_id"]
        client_name = client["name"]

        # Gather context for this client
        context = _gather_client_context(conn, client_id)

        # Generate message
        message = _generate_message(
            client_name=client_name,
            context=context,
            api_key=api_key,
        )

        draft = LineDraft(
            client_id=client_id,
            client_name=client_name,
            message=message,
            generated_at=datetime.now(timezone.utc).isoformat(),
            sent=False,
        )
        drafts.append(draft)

        # Store in DB
        _store_draft(conn, draft, week)

    logger.info("Generated %d LINE drafts for week %s", len(drafts), week)
    return drafts


def generate_draft_for_client(
    conn: sqlite3.Connection,
    client_id: str,
    week: Optional[str] = None,
    api_key: Optional[str] = None,
) -> LineDraft:
    """Generate a single LINE draft for one client.

    Args:
        conn: SQLite connection.
        client_id: Client to generate draft for.
        week: ISO week string.
        api_key: Anthropic API key.

    Returns:
        LineDraft object.

    Raises:
        ValueError: If client not found.
    """
    if week is None:
        now = datetime.now(timezone.utc)
        week = f"{now.year}-W{now.isocalendar()[1]:02d}"

    client = _get_client(conn, client_id)
    if client is None:
        raise ValueError(f"Client {client_id} not found")

    context = _gather_client_context(conn, client_id)
    message = _generate_message(
        client_name=client["name"],
        context=context,
        api_key=api_key,
    )

    draft = LineDraft(
        client_id=client_id,
        client_name=client["name"],
        message=message,
        generated_at=datetime.now(timezone.utc).isoformat(),
        sent=False,
    )

    _store_draft(conn, draft, week)
    return draft


def get_drafts_for_week(
    conn: sqlite3.Connection, week: str
) -> List[dict]:
    """Get all drafts for a given week."""
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT * FROM line_drafts WHERE week = ? ORDER BY generated_at",
        (week,),
    ).fetchall()
    return [dict(r) for r in rows]


def mark_draft_reviewed(conn: sqlite3.Connection, draft_id: str) -> bool:
    """Mark a draft as reviewed by advisor."""
    with conn:
        cursor = conn.execute(
            "UPDATE line_drafts SET reviewed_at = datetime('now') WHERE draft_id = ?",
            (draft_id,),
        )
    return cursor.rowcount > 0


def mark_draft_sent(conn: sqlite3.Connection, draft_id: str) -> bool:
    """Mark a draft as sent."""
    with conn:
        cursor = conn.execute(
            "UPDATE line_drafts SET sent_at = datetime('now') WHERE draft_id = ?",
            (draft_id,),
        )
    return cursor.rowcount > 0


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _get_all_clients(conn: sqlite3.Connection) -> List[dict]:
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT client_id, name FROM clients ORDER BY name"
    ).fetchall()
    return [dict(r) for r in rows]


def _get_client(conn: sqlite3.Connection, client_id: str) -> Optional[dict]:
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT client_id, name FROM clients WHERE client_id = ?",
        (client_id,),
    ).fetchone()
    return dict(row) if row else None


def _gather_client_context(conn: sqlite3.Connection, client_id: str) -> dict:
    """Gather portfolio and attribution context for message generation."""
    conn.row_factory = sqlite3.Row

    # Get portfolio (deduplicated by fund)
    portfolio_rows = conn.execute(
        "SELECT fund_code, cost_basis FROM client_portfolios WHERE client_id = ?",
        (client_id,),
    ).fetchall()

    fund_codes = list(set(r["fund_code"] for r in portfolio_rows))
    fund_values = {r["fund_code"]: r["cost_basis"] for r in portfolio_rows}
    total_value = sum(fund_values.values())

    # Calculate simple portfolio return if data available
    portfolio_return = None
    if fund_codes and total_value > 0:
        weighted_return = 0.0
        has_returns = False
        for code in fund_codes:
            weight = fund_values.get(code, 0) / total_value
            # Get fund-level return from fund_holdings
            fh_rows = conn.execute(
                "SELECT weight, return_rate FROM fund_holdings WHERE fund_code = ?",
                (code,),
            ).fetchall()
            if fh_rows:
                fund_ret = sum(
                    (r["weight"] or 0) * (r["return_rate"] or 0) for r in fh_rows
                )
                weighted_return += weight * fund_ret
                has_returns = True
        if has_returns:
            portfolio_return = weighted_return

    # Top holdings by value
    top_funds = sorted(fund_values.items(), key=lambda x: x[1], reverse=True)[:3]

    return {
        "fund_codes": fund_codes,
        "num_funds": len(fund_codes),
        "total_value": total_value,
        "portfolio_return": portfolio_return,
        "top_funds": top_funds,
    }


def _generate_message(
    client_name: str,
    context: dict,
    api_key: Optional[str] = None,
) -> str:
    """Generate a personalized LINE message via Claude API or fallback."""
    try:
        import anthropic
        from config.settings import ANTHROPIC_API_KEY, AI_TIMEOUT_SECONDS

        key = api_key or ANTHROPIC_API_KEY
        if not key:
            return _fallback_message(client_name, context)

        prompt = _build_prompt(client_name, context)
        client = anthropic.Anthropic(api_key=key)
        message = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=256,
            timeout=AI_TIMEOUT_SECONDS,
            messages=[{"role": "user", "content": prompt}],
        )

        text = message.content[0].text.strip()
        # Enforce 200 char limit
        if len(text) > 200:
            text = text[:197] + "..."
        return text

    except Exception as e:
        logger.warning("AI LINE draft failed for %s: %s — using fallback", client_name, e)
        return _fallback_message(client_name, context)


def _build_prompt(client_name: str, context: dict) -> str:
    """Build Claude prompt for LINE message generation."""
    portfolio_info = ""
    if context["num_funds"] > 0:
        portfolio_info = f"持有 {context['num_funds']} 檔基金"
        if context["total_value"] > 0:
            portfolio_info += f"，總市值約 NT${context['total_value']:,.0f}"

    return_info = ""
    if context["portfolio_return"] is not None:
        ret_pct = context["portfolio_return"] * 100
        return_info = f"近期投組報酬率約 {ret_pct:.1f}%"

    top_funds_info = ""
    if context["top_funds"]:
        top_funds_info = "主要持倉：" + "、".join(
            f"{code}" for code, _ in context["top_funds"]
        )

    return f"""你是一位親切的台灣理財顧問，要發 LINE 訊息給客戶「{client_name}」。

客戶資訊：
- {portfolio_info}
- {return_info}
- {top_funds_info}

## 規則
1. 用繁體中文，語氣親切但專業，像朋友聊天
2. 200 字以內
3. 開頭用一個合適的 emoji
4. 提及客戶的實際持倉或報酬（如果有資料）
5. 給一個簡短的市場觀點或行動建議
6. 不要用敬語「您好」，直接開始

直接輸出訊息文字，不要加引號或其他格式。"""


def _fallback_message(client_name: str, context: dict) -> str:
    """Rule-based fallback LINE message."""
    parts = []

    if context["portfolio_return"] is not None:
        ret = context["portfolio_return"]
        if ret > 0:
            parts.append(f"📈 {client_name}，您的投組近期表現不錯，報酬率 {ret*100:.1f}%")
        elif ret < 0:
            parts.append(f"📊 {client_name}，近期市場波動較大，投組報酬率 {ret*100:.1f}%，建議持續定期定額")
        else:
            parts.append(f"📊 {client_name}，投組表現持平，建議檢視是否需要調整配置")
    else:
        parts.append(f"👋 {client_name}，提醒您定期檢視投資組合")

    if context["num_funds"] > 0:
        parts.append(f"目前持有 {context['num_funds']} 檔基金")

    if context["top_funds"]:
        top_code = context["top_funds"][0][0]
        parts.append(f"主要持倉 {top_code} 可留意近期走勢")

    parts.append("有任何問題隨時找我聊！")

    message = "，".join(parts[:3]) + "。" + parts[-1]
    if len(message) > 200:
        message = message[:197] + "..."
    return message


def _store_draft(
    conn: sqlite3.Connection, draft: LineDraft, week: str
) -> str:
    """Store a draft in the line_drafts table."""
    draft_id = str(uuid.uuid4())[:8]
    with conn:
        conn.execute(
            """INSERT INTO line_drafts
               (draft_id, client_id, message, week, generated_at)
               VALUES (?, ?, ?, ?, ?)""",
            (draft_id, draft.client_id, draft.message, week, draft.generated_at),
        )
    return draft_id
