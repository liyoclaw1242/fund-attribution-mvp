"""Inaction Cost Visualizer — 不投資的代價視覺化

Standalone sales tool: helps advisors show fixed-deposit clients
why they should invest, by visualizing 10-year purchasing power erosion.

No dependency on other modules — pure calculation + Matplotlib chart.
"""

import io

import streamlit as st

st.set_page_config(
    page_title="不投資的代價",
    page_icon="💸",
    layout="wide",
)

st.title("💸 不投資的代價")
st.caption("Inaction Cost Visualizer — 幫助客戶理解閒置資金的購買力侵蝕")

# --- Sidebar Parameters ---
st.sidebar.header("假設參數")
cpi_rate = st.sidebar.slider("CPI 通膨率 (%)", 0.5, 5.0, 2.0, 0.1) / 100.0
deposit_rate = st.sidebar.slider("定存利率 (%)", 0.5, 5.0, 1.5, 0.1) / 100.0
portfolio_rate = st.sidebar.slider("穩健投資組合報酬率 (%)", 2.0, 12.0, 6.0, 0.5) / 100.0

# --- Main Input ---
cash_amount = st.number_input(
    "閒置資金金額 (TWD)",
    min_value=10_000,
    max_value=100_000_000,
    value=1_000_000,
    step=100_000,
    format="%d",
    help="輸入客戶目前的閒置存款金額",
)

if cash_amount > 0:
    from report.inaction_chart import generate_inaction_chart

    fig, summary = generate_inaction_chart(
        cash_amount=cash_amount,
        cpi_rate=cpi_rate,
        deposit_rate=deposit_rate,
        portfolio_rate=portfolio_rate,
        years=10,
    )

    # --- Chart ---
    st.pyplot(fig, use_container_width=True)

    import matplotlib.pyplot as plt
    plt.close(fig)

    # --- Summary Metrics ---
    sum_cols = st.columns(3)
    sum_cols[0].metric(
        "現金放床底（10年後購買力）",
        f"${summary['mattress_final']:,.0f}",
        delta=f"${summary['mattress_final'] - cash_amount:,.0f}",
        delta_color="inverse",
    )
    sum_cols[1].metric(
        "定存（10年後購買力）",
        f"${summary['deposit_final']:,.0f}",
        delta=f"${summary['deposit_final'] - cash_amount:,.0f}",
        delta_color="inverse" if summary["deposit_final"] < cash_amount else "normal",
    )
    sum_cols[2].metric(
        "穩健投資（10年後購買力）",
        f"${summary['portfolio_final']:,.0f}",
        delta=f"+${summary['portfolio_final'] - cash_amount:,.0f}",
    )

    st.caption(
        f"假設條件：通膨 {cpi_rate * 100:.1f}%、定存利率 {deposit_rate * 100:.1f}%、"
        f"投資組合年化報酬 {portfolio_rate * 100:.1f}%。所有數值為實質購買力（扣除通膨）。"
    )

    st.divider()

    # --- Download PNG ---
    buf = io.BytesIO()
    fig_dl, _ = generate_inaction_chart(
        cash_amount=cash_amount,
        cpi_rate=cpi_rate,
        deposit_rate=deposit_rate,
        portfolio_rate=portfolio_rate,
        years=10,
    )
    fig_dl.savefig(buf, dpi=180, bbox_inches="tight", facecolor="white", format="png")
    plt.close(fig_dl)
    buf.seek(0)

    st.download_button(
        "📥 下載圖表 (PNG)",
        data=buf.getvalue(),
        file_name="inaction_cost.png",
        mime="image/png",
        use_container_width=True,
    )
