"""Fund Attribution Analysis MVP — Streamlit Application.

基金歸因分析系統
Target: Professional Financial Advisors in Taiwan
"""

import streamlit as st

st.set_page_config(
    page_title="基金歸因分析系統",
    page_icon="📊",
    layout="wide",
)

st.title("📊 基金歸因分析系統")
st.caption("Fund Attribution Analysis — Brinson-Fachler Model")

# --- Input Section ---
col1, col2 = st.columns(2)

with col1:
    input_method = st.radio("資料來源", ["輸入基金代碼", "上傳 CSV/Excel"])

    if input_method == "輸入基金代碼":
        fund_code = st.text_input("基金代碼", placeholder="e.g. 0050")
    else:
        uploaded_file = st.file_uploader(
            "上傳持股資料",
            type=["csv", "xlsx"],
            help="欄位: industry, weight, return_rate",
        )

with col2:
    benchmark = st.selectbox(
        "基準指數",
        ["加權股價報酬指數", "電子類報酬指數", "金融保險類報酬指數"],
    )
    period = st.date_input("分析期間")
    brinson_mode = st.radio("歸因模式", ["BF2 (二因子)", "BF3 (三因子)"])

advisor_name = st.sidebar.text_input("理財顧問姓名", help="將顯示於 PDF 報告")

run = st.button("🚀 開始分析", type="primary", use_container_width=True)

# --- Results Section (placeholder) ---
if run:
    st.info("⚠️ 系統建置中 — 各模組尚未實作，請參考 GitHub Issues。")

    # Placeholder KPI cards
    kpi_cols = st.columns(5)
    kpi_cols[0].metric("基金報酬", "—")
    kpi_cols[1].metric("基準報酬", "—")
    kpi_cols[2].metric("超額報酬", "—")
    kpi_cols[3].metric("配置效果", "—")
    kpi_cols[4].metric("選股效果", "—")

    st.divider()
    st.subheader("瀑布圖")
    st.empty()  # chart placeholder

    st.subheader("產業貢獻")
    st.empty()  # chart placeholder

    # AI summary tabs
    tab1, tab2, tab3 = st.tabs(["LINE 摘要", "PDF 摘要", "顧問筆記"])
    with tab1:
        st.text_area("LINE 訊息", value="（AI 摘要尚未實作）", height=80)
    with tab2:
        st.text_area("PDF 摘要", value="（AI 摘要尚未實作）", height=120)
    with tab3:
        st.text_area("顧問筆記", value="（AI 摘要尚未實作）", height=60)

    # Export sidebar
    st.sidebar.divider()
    st.sidebar.download_button("📥 下載 PNG", data=b"", file_name="waterfall.png", disabled=True)
    st.sidebar.download_button("📥 下載 PDF", data=b"", file_name="report.pdf", disabled=True)
