"""Goal Tracker Dashboard — 目標追蹤儀表板

Monte Carlo simulation-based goal tracking for financial advisors.
Client sets a financial goal → sees success probability, fan chart,
and adjustment suggestions.

Depends on engine.goal_simulator for simulate_goal() (Issue #41).
Falls back to demo data when engine is not yet available.
"""

import io
import uuid
from datetime import datetime

import matplotlib.pyplot as plt
import streamlit as st

st.set_page_config(
    page_title="目標追蹤",
    page_icon="🎯",
    layout="wide",
)

st.title("🎯 目標追蹤")
st.caption("Goal Tracker — 設定您的財務目標，透過蒙地卡羅模擬分析達成機率")


# --- Constants ---
GOAL_TYPES = {
    "retirement": "🏦 退休規劃",
    "house": "🏠 購屋計畫",
    "education": "🎓 子女教育",
}

RISK_LABELS = {
    "conservative": "保守",
    "moderate": "穩健",
    "aggressive": "積極",
}

_CURRENT_YEAR = datetime.now().year


# --- Helper: probability color ---
def _prob_color(prob: float) -> str:
    """Return color based on success probability."""
    if prob >= 0.80:
        return "#1D9E75"  # green
    elif prob >= 0.50:
        return "#BA7517"  # amber
    return "#E24B4A"  # red


def _prob_label(prob: float) -> str:
    """Return Chinese label for probability level."""
    if prob >= 0.80:
        return "目標達成機率高"
    elif prob >= 0.50:
        return "建議調整方案"
    return "需要大幅調整"


def _format_twd(amount: float) -> str:
    """Format TWD amount in 萬 units."""
    return f"{amount / 10_000:,.0f} 萬"


# --- Simulation ---
def _run_simulation(goal_config: dict) -> dict:
    """Run Monte Carlo simulation. Falls back to demo if engine unavailable."""
    try:
        from engine.goal_simulator import simulate_goal
        from interfaces import GoalConfig

        config = GoalConfig(
            target_amount=goal_config["target_amount"],
            target_year=goal_config["target_year"],
            monthly_contribution=goal_config["monthly_contribution"],
            risk_tolerance=goal_config["risk_tolerance"],
            goal_type=goal_config["goal_type"],
            current_savings=goal_config.get("current_savings", 0),
        )
        return simulate_goal(config)
    except (ImportError, NotImplementedError):
        # Demo fallback — generate plausible mock data
        return _demo_simulation(goal_config)


def _demo_simulation(config: dict) -> dict:
    """Generate demo simulation result for UI development."""
    import numpy as np

    target = config["target_amount"]
    years = config["target_year"] - _CURRENT_YEAR
    monthly = config["monthly_contribution"]
    current = config.get("current_savings", 0)

    # Simple compound growth model for demo
    risk_rates = {"conservative": 0.04, "moderate": 0.07, "aggressive": 0.10}
    rate = risk_rates.get(config["risk_tolerance"], 0.07)
    vol = rate * 0.6  # rough volatility

    year_list = list(range(_CURRENT_YEAR, config["target_year"] + 1))
    n = len(year_list)

    # Build paths
    median_path = []
    p10_path = []
    p90_path = []
    for i in range(n):
        t = i
        base = current + monthly * 12 * t
        growth = base * (1 + rate) ** t if t > 0 else base
        median_path.append(growth)
        p90_path.append(growth * (1 + vol * 1.3) ** max(0, t * 0.5))
        p10_path.append(growth * (1 - vol * 0.8) ** max(0, t * 0.3))

    median_final = median_path[-1] if median_path else target * 0.7
    prob = min(0.95, max(0.15, median_final / target))

    # Suggestions when probability < 80%
    suggestions = []
    if prob < 0.80:
        extra_monthly = monthly * 0.3
        suggestions.append(
            f"每月增加 {_format_twd(extra_monthly)} 投入，達成機率可提升約 12%"
        )
        suggestions.append(
            f"將目標延後 2 年至 {config['target_year'] + 2} 年，達成機率可提升約 15%"
        )
        if config["risk_tolerance"] != "aggressive":
            suggestions.append(
                "調整為積極型配置，預期報酬提升但波動增加，達成機率可提升約 8%"
            )

    return {
        "success_probability": prob,
        "median_outcome": median_final,
        "p10_outcome": p10_path[-1] if p10_path else target * 0.4,
        "p90_outcome": p90_path[-1] if p90_path else target * 1.3,
        "target_amount": target,
        "years_to_goal": years,
        "num_paths": 10000,
        "suggestions": suggestions,
        # Extra data for chart
        "_years": year_list,
        "_p10": p10_path,
        "_median": median_path,
        "_p90": p90_path,
        "_is_demo": True,
    }


# --- Goal CRUD (session state) ---
if "goals" not in st.session_state:
    st.session_state.goals = []

if "editing_goal" not in st.session_state:
    st.session_state.editing_goal = None


def _save_goal(goal: dict) -> None:
    """Save or update a goal in session state."""
    existing = [g for g in st.session_state.goals if g["goal_id"] == goal["goal_id"]]
    if existing:
        idx = st.session_state.goals.index(existing[0])
        st.session_state.goals[idx] = goal
    else:
        st.session_state.goals.append(goal)


def _delete_goal(goal_id: str) -> None:
    """Delete a goal from session state."""
    st.session_state.goals = [g for g in st.session_state.goals if g["goal_id"] != goal_id]


# --- API persistence helpers ---
def _save_goal_to_api(goal: dict) -> None:
    """Persist goal via FastAPI. No-op if API unavailable."""
    try:
        from utils.api_client import create_goal
        create_goal(
            client_id=goal.get("client_id", "default"),
            goal_type=goal["goal_type"],
            target_amount=goal["target_amount"],
            target_year=goal["target_year"],
            monthly_contribution=goal["monthly_contribution"],
            risk_tolerance=goal["risk_tolerance"],
        )
    except Exception:
        pass  # API not available — session state is primary


def _load_goals_from_api() -> list[dict]:
    """Load goals via FastAPI. Returns empty list if unavailable."""
    try:
        from utils.api_client import list_goals
        return list_goals("default")
    except Exception:
        return []


# Load from API on first run
if "goals_loaded" not in st.session_state:
    api_goals = _load_goals_from_api()
    if api_goals:
        st.session_state.goals = api_goals
    st.session_state.goals_loaded = True


# ===================================================================
# Main Layout
# ===================================================================

# --- Goal Setup Form (left) + Results (right) ---
form_col, spacer, result_col = st.columns([1, 0.05, 2])

with form_col:
    st.subheader("目標設定")

    goal_type = st.selectbox(
        "目標類型",
        options=list(GOAL_TYPES.keys()),
        format_func=lambda x: GOAL_TYPES[x],
    )

    target_amount = st.number_input(
        "目標金額 (萬元)",
        min_value=100,
        max_value=100_000,
        value=2000,
        step=100,
        help="以萬元為單位，例如 2000 = 2,000 萬",
    )

    target_year = st.number_input(
        "目標年份",
        min_value=_CURRENT_YEAR + 1,
        max_value=_CURRENT_YEAR + 40,
        value=min(_CURRENT_YEAR + 20, _CURRENT_YEAR + 40),
        step=1,
    )

    monthly_contribution = st.number_input(
        "每月投入金額 (萬元)",
        min_value=0.1,
        max_value=1000.0,
        value=3.5,
        step=0.5,
        help="每月定期投入的金額（萬元）",
    )

    current_savings = st.number_input(
        "目前儲蓄 (萬元)",
        min_value=0.0,
        max_value=100_000.0,
        value=0.0,
        step=100.0,
        help="目前已有的儲蓄金額（萬元）",
    )

    st.markdown("**風險承受度**")
    risk_cols = st.columns(3)
    risk_tolerance = "moderate"
    for i, (key, label) in enumerate(RISK_LABELS.items()):
        with risk_cols[i]:
            if st.button(label, use_container_width=True, key=f"risk_{key}"):
                st.session_state.selected_risk = key
    risk_tolerance = st.session_state.get("selected_risk", "moderate")

    # Show active risk indicator
    st.caption(f"已選擇：{RISK_LABELS[risk_tolerance]}")

    simulate = st.button("▶ 開始模擬", type="primary", use_container_width=True)


# --- Run Simulation ---
if simulate:
    goal_config = {
        "goal_type": goal_type,
        "target_amount": target_amount * 10_000,  # convert 萬 → TWD
        "target_year": target_year,
        "monthly_contribution": monthly_contribution * 10_000,
        "risk_tolerance": risk_tolerance,
        "current_savings": current_savings * 10_000,
    }

    with st.spinner("模擬計算中..."):
        result = _run_simulation(goal_config)

    st.session_state.last_result = result
    st.session_state.last_config = goal_config

# --- Display Results ---
if "last_result" in st.session_state:
    result = st.session_state.last_result
    config = st.session_state.last_config
    prob = result["success_probability"]
    color = _prob_color(prob)

    with result_col:
        st.subheader("模擬結果")

        if result.get("_is_demo"):
            st.caption("⚠️ 目前使用展示資料 — 蒙地卡羅引擎完成後將自動切換（Issue #41）")

        # --- Probability Display ---
        prob_col, stat_cols_container = st.columns([1, 2])

        with prob_col:
            # Large probability number
            st.markdown(
                f"""
                <div style="text-align: center; padding: 16px;">
                    <div style="font-size: 56px; font-weight: 700; color: {color}; line-height: 1;">
                        {prob * 100:.0f}%
                    </div>
                    <div style="font-size: 14px; color: #666; margin-top: 4px;">達成機率</div>
                    <div style="font-size: 12px; color: {color}; margin-top: 2px;">
                        {_prob_label(prob)}
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )

        with stat_cols_container:
            s1, s2, s3 = st.columns(3)
            s1.metric("中位數 P50", _format_twd(result["median_outcome"]))
            s2.metric("樂觀 P90", _format_twd(result["p90_outcome"]))
            s3.metric("悲觀 P10", _format_twd(result["p10_outcome"]))

        # --- Fan Chart ---
        if "_years" in result:
            from report.fan_chart import generate_fan_chart

            fig = generate_fan_chart(
                years=result["_years"],
                p10=result["_p10"],
                median=result["_median"],
                p90=result["_p90"],
                target_amount=config["target_amount"],
            )
            st.pyplot(fig, use_container_width=True)
            plt.close(fig)

            # Download button
            buf = io.BytesIO()
            fig_dl = generate_fan_chart(
                years=result["_years"],
                p10=result["_p10"],
                median=result["_median"],
                p90=result["_p90"],
                target_amount=config["target_amount"],
            )
            fig_dl.savefig(buf, dpi=180, bbox_inches="tight", facecolor="white", format="png")
            plt.close(fig_dl)
            buf.seek(0)
            st.download_button(
                "📥 下載圖表 (PNG)",
                data=buf.getvalue(),
                file_name="goal_fan_chart.png",
                mime="image/png",
            )

    # --- Suggestion Cards ---
    if result.get("suggestions"):
        st.divider()
        st.subheader("💡 改善建議")

        suggestion_icons = ["💰", "📅", "📈"]
        suggestion_titles = ["增加每月投入", "延長目標年限", "調整風險配置"]
        suggestion_improvements = ["+12% 機率", "+15% 機率", "+8% 機率"]

        cols = st.columns(min(len(result["suggestions"]), 3))
        for i, suggestion in enumerate(result["suggestions"][:3]):
            with cols[i]:
                icon = suggestion_icons[i] if i < len(suggestion_icons) else "💡"
                title = suggestion_titles[i] if i < len(suggestion_titles) else "建議"
                improvement = suggestion_improvements[i] if i < len(suggestion_improvements) else ""

                st.markdown(
                    f"""
                    <div style="
                        padding: 16px;
                        border-radius: 12px;
                        border: 1px solid #e5e5e5;
                        background: #fafafa;
                    ">
                        <div style="font-size: 24px; margin-bottom: 8px;">{icon}</div>
                        <div style="font-weight: 600; margin-bottom: 4px;">{title}</div>
                        <div style="font-size: 13px; color: #666; margin-bottom: 8px;">
                            {suggestion}
                        </div>
                        <div style="
                            display: inline-block;
                            padding: 2px 8px;
                            border-radius: 12px;
                            background: #e8f5e9;
                            color: #1D9E75;
                            font-size: 12px;
                            font-weight: 600;
                        ">{improvement}</div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

    # --- Save Goal ---
    if simulate:
        st.divider()
        save_col1, save_col2 = st.columns([3, 1])
        with save_col2:
            if st.button("💾 儲存此目標", use_container_width=True):
                goal = {
                    "goal_id": str(uuid.uuid4())[:8],
                    "client_id": "default",
                    "goal_type": config["goal_type"],
                    "target_amount": config["target_amount"],
                    "target_year": config["target_year"],
                    "monthly_contribution": config["monthly_contribution"],
                    "risk_tolerance": config["risk_tolerance"],
                    "probability": prob,
                }
                _save_goal(goal)
                _save_goal_to_api(goal)
                st.success("目標已儲存！")
                st.rerun()

# --- Saved Goals ---
if st.session_state.goals:
    st.divider()
    header_col, add_col = st.columns([4, 1])
    with header_col:
        st.subheader("📋 已儲存目標")

    for goal in st.session_state.goals:
        goal_type_label = GOAL_TYPES.get(goal.get("goal_type", ""), "🎯 目標")
        prob_val = goal.get("probability", 0)
        prob_color = _prob_color(prob_val)

        with st.container():
            g1, g2, g3, g4 = st.columns([3, 2, 1, 1])
            with g1:
                st.markdown(f"**{goal_type_label}**")
                st.caption(
                    f"目標 {_format_twd(goal.get('target_amount', 0))} · "
                    f"{goal.get('target_year', '')} 年 · "
                    f"每月 {_format_twd(goal.get('monthly_contribution', 0))} · "
                    f"{RISK_LABELS.get(goal.get('risk_tolerance', ''), '')}"
                )
            with g2:
                st.markdown(
                    f"<span style='color:{prob_color}; font-weight:700; font-size:18px;'>"
                    f"{prob_val * 100:.0f}%</span>",
                    unsafe_allow_html=True,
                )
            with g3:
                if st.button("✏️", key=f"edit_{goal['goal_id']}", help="編輯"):
                    st.session_state.editing_goal = goal["goal_id"]
                    st.rerun()
            with g4:
                if st.button("🗑️", key=f"del_{goal['goal_id']}", help="刪除"):
                    _delete_goal(goal["goal_id"])
                    st.rerun()
