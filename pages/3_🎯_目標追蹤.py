"""Goal Tracker Dashboard — 目標追蹤儀表板

Monte Carlo simulation: client sets a financial goal, sees success
probability, fan chart, and adjustment suggestions.

Feature F-301 FE.
"""

import io

import streamlit as st

st.set_page_config(
    page_title="目標追蹤儀表板",
    page_icon="🎯",
    layout="wide",
)

st.title("🎯 目標追蹤儀表板")
st.caption("Goal Tracker — Monte Carlo 模擬你的財務目標達成機率")

# --- Goal Setup Form ---
st.subheader("設定目標")

col1, col2 = st.columns(2)

with col1:
    goal_type = st.selectbox(
        "目標類型",
        ["retirement", "house", "education"],
        format_func=lambda x: {"retirement": "退休", "house": "購屋", "education": "子女教育"}[x],
    )
    target_amount = st.number_input(
        "目標金額 (TWD)",
        min_value=100_000,
        max_value=100_000_000,
        value=5_000_000,
        step=500_000,
        format="%d",
    )
    current_savings = st.number_input(
        "目前已存金額 (TWD)",
        min_value=0,
        max_value=100_000_000,
        value=500_000,
        step=100_000,
        format="%d",
    )

with col2:
    import datetime
    current_year = datetime.datetime.now().year

    target_year = st.number_input(
        "目標年份",
        min_value=current_year + 1,
        max_value=current_year + 50,
        value=current_year + 10,
        step=1,
    )
    monthly_contribution = st.number_input(
        "每月投入金額 (TWD)",
        min_value=0,
        max_value=1_000_000,
        value=20_000,
        step=1_000,
        format="%d",
    )
    risk_tolerance = st.selectbox(
        "風險承受度",
        ["conservative", "moderate", "aggressive"],
        index=1,
        format_func=lambda x: {
            "conservative": "保守型 (預期 4%, 波動 5%)",
            "moderate": "穩健型 (預期 7%, 波動 12%)",
            "aggressive": "積極型 (預期 10%, 波動 18%)",
        }[x],
    )

run_sim = st.button("🚀 開始模擬", type="primary", use_container_width=True)

if run_sim:
    from interfaces import GoalConfig
    from engine.goal_tracker import simulate_goal
    from report.goal_chart import generate_goal_chart
    import matplotlib.pyplot as plt

    goal = GoalConfig(
        target_amount=target_amount,
        target_year=target_year,
        monthly_contribution=monthly_contribution,
        risk_tolerance=risk_tolerance,
        goal_type=goal_type,
        current_savings=current_savings,
    )

    with st.status("模擬進行中...", expanded=True) as status:
        st.write("🎲 執行 Monte Carlo 模擬（1,000 條路徑）...")
        try:
            result = simulate_goal(goal, seed=42)
        except ValueError as e:
            st.error(str(e))
            status.update(label="模擬失敗", state="error")
            st.stop()

        st.write("✅ 模擬完成")
        st.write("📊 產生圖表...")

        fig = generate_goal_chart(
            initial_balance=current_savings,
            monthly_contribution=monthly_contribution,
            risk_tolerance=risk_tolerance,
            years=result.years_to_goal,
            target_amount=target_amount,
            success_probability=result.success_probability,
        )

        st.write("✅ 圖表產生完成")
        status.update(label="模擬完成", state="complete")

    # --- Success Probability (prominent) ---
    prob = result.success_probability
    if prob >= 0.80:
        prob_color = "green"
        prob_icon = "✅"
    elif prob >= 0.50:
        prob_color = "orange"
        prob_icon = "⚠️"
    else:
        prob_color = "red"
        prob_icon = "🚨"

    st.markdown(
        f"<div style='text-align:center; padding:20px;'>"
        f"<span style='font-size:20px;'>{prob_icon} 達標機率</span><br>"
        f"<span style='font-size:64px; font-weight:bold; color:{prob_color};'>"
        f"{prob:.0%}</span>"
        f"</div>",
        unsafe_allow_html=True,
    )

    # --- KPI Row ---
    kpi_cols = st.columns(4)
    kpi_cols[0].metric("目標金額", f"${target_amount:,.0f}")
    kpi_cols[1].metric("中位數結果 (P50)", f"${result.median_outcome:,.0f}")
    kpi_cols[2].metric(
        "悲觀情境 (P10)",
        f"${result.p10_outcome:,.0f}",
        delta=f"${result.p10_outcome - target_amount:,.0f}",
        delta_color="inverse" if result.p10_outcome < target_amount else "normal",
    )
    kpi_cols[3].metric(
        "樂觀情境 (P90)",
        f"${result.p90_outcome:,.0f}",
        delta=f"+${result.p90_outcome - target_amount:,.0f}",
    )

    st.divider()

    # --- Fan Chart ---
    st.subheader("Monte Carlo 模擬圖")
    st.pyplot(fig, use_container_width=True)
    plt.close(fig)

    # Download chart
    buf = io.BytesIO()
    fig_dl = generate_goal_chart(
        initial_balance=current_savings,
        monthly_contribution=monthly_contribution,
        risk_tolerance=risk_tolerance,
        years=result.years_to_goal,
        target_amount=target_amount,
        success_probability=result.success_probability,
    )
    fig_dl.savefig(buf, dpi=180, bbox_inches="tight", facecolor="white", format="png")
    plt.close(fig_dl)
    buf.seek(0)

    st.download_button(
        "📥 下載模擬圖表 (PNG)",
        data=buf.getvalue(),
        file_name="goal_monte_carlo.png",
        mime="image/png",
    )

    st.divider()

    # --- Suggestions ---
    if result.suggestions:
        st.subheader("💡 調整建議")
        if prob < 0.80:
            st.info(f"目前達標機率 {prob:.0%} 低於 80%，以下是提高機率的建議：", icon="💡")

        for i, suggestion in enumerate(result.suggestions, 1):
            st.markdown(f"**{i}.** {suggestion}")
    else:
        st.success("🎉 目前計畫達標機率良好，繼續保持！", icon="🎉")

    st.divider()

    # --- Assumptions ---
    with st.expander("模擬假設說明"):
        risk_labels = {
            "conservative": ("保守型", "4%", "5%"),
            "moderate": ("穩健型", "7%", "12%"),
            "aggressive": ("積極型", "10%", "18%"),
        }
        label, mean, std = risk_labels[risk_tolerance]
        st.markdown(f"""
- **風險類型**: {label}
- **預期年化報酬**: {mean}
- **年化波動度**: {std}
- **模擬路徑數**: {result.num_paths:,} 條
- **方法**: 常態分佈 Monte Carlo 模擬（月度步進）
- **注意**: 此為簡化模型，實際投資績效可能與模擬結果有顯著差異。
        """)
