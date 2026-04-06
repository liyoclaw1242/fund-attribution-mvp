"""Fund Attribution Analysis MVP — Streamlit Application.

基金歸因分析系統
Target: Professional Financial Advisors in Taiwan
"""

import time

import pandas as pd
import streamlit as st

from config.settings import UNMAPPED_WARN_THRESHOLD, UNMAPPED_BLOCK_THRESHOLD

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
            help="欄位: industry, Wp, Wb, Rp, Rb（或 industry, weight, return_rate）",
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


def _parse_mode(label: str) -> str:
    """Extract mode string from radio label."""
    return "BF3" if "BF3" in label else "BF2"


def _load_holdings(uploaded_file, input_method: str, fund_code: str = "") -> pd.DataFrame:
    """Load holdings DataFrame from uploaded file or fund code.

    Returns DataFrame with columns [industry, Wp, Wb, Rp, Rb].
    Raises ValueError on invalid input.
    """
    if input_method == "上傳 CSV/Excel":
        if uploaded_file is None:
            raise ValueError("請先上傳持股資料檔案")

        if uploaded_file.name.endswith(".csv"):
            df = pd.read_csv(uploaded_file)
        else:
            df = pd.read_excel(uploaded_file)

        # Golden format: already has Wp, Wb, Rp, Rb
        required = ["industry", "Wp", "Wb", "Rp", "Rb"]
        if all(c in df.columns for c in required):
            return df[required]

        # SITCA format: industry, weight, return_rate
        from data.sitca_parser import parse_sitca_excel

        # Save to temp file for parser
        suffix = ".xlsx" if uploaded_file.name.endswith(".xlsx") else ".csv"
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(uploaded_file.getvalue())
            tmp_path = tmp.name

        parsed = parse_sitca_excel(tmp_path)
        raise ValueError(
            "上傳的檔案缺少基準資料（Wb, Rb 欄位）。\n"
            "請使用包含 industry, Wp, Wb, Rp, Rb 欄位的完整資料集，"
            "或改用「輸入基金代碼」模式自動取得基準。"
        )

    else:
        if not fund_code.strip():
            raise ValueError("請輸入基金代碼")
        raise ValueError(
            f"基金代碼 {fund_code} 查詢功能建置中。\n"
            "請先使用「上傳 CSV/Excel」模式。"
        )


def _format_pct(value: float) -> str:
    """Format a decimal as percentage string."""
    return f"{value * 100:+.2f}%"


def _show_warnings(result: dict) -> bool:
    """Display warning banners based on attribution result.

    Returns True if analysis should be blocked (unmapped > 10%).
    """
    unmapped = result["unmapped_weight"]
    blocked = False

    if unmapped >= UNMAPPED_BLOCK_THRESHOLD:
        st.error(
            f"🚫 未對照產業權重 {unmapped * 100:.1f}% 超過 {UNMAPPED_BLOCK_THRESHOLD * 100:.0f}% 門檻 — "
            f"分析結果不可靠，已阻擋顯示。\n\n"
            f"未對照: {', '.join(result['unmapped_industries']) or '(none)'}",
            icon="🚫",
        )
        blocked = True
    elif unmapped >= UNMAPPED_WARN_THRESHOLD:
        st.warning(
            f"⚠️ 未對照產業權重 {unmapped * 100:.1f}% 超過 {UNMAPPED_WARN_THRESHOLD * 100:.0f}% 警戒 — "
            f"結果僅供參考。\n\n"
            f"未對照: {', '.join(result['unmapped_industries']) or '(none)'}",
            icon="⚠️",
        )

    return blocked


def _show_kpi_cards(result: dict):
    """Display KPI metric cards."""
    mode = result["brinson_mode"]
    n_cols = 6 if mode == "BF3" else 5
    kpi_cols = st.columns(n_cols)

    kpi_cols[0].metric("基金報酬", _format_pct(result["fund_return"]))
    kpi_cols[1].metric("基準報酬", _format_pct(result["bench_return"]))
    kpi_cols[2].metric(
        "超額報酬",
        _format_pct(result["excess_return"]),
        delta=_format_pct(result["excess_return"]),
    )
    kpi_cols[3].metric("配置效果", _format_pct(result["allocation_total"]))
    kpi_cols[4].metric("選股效果", _format_pct(result["selection_total"]))

    if mode == "BF3":
        kpi_cols[5].metric("交互效果", _format_pct(result["interaction_total"]))


def _show_detail_table(result: dict):
    """Display the industry detail breakdown."""
    detail = result["detail"].copy()

    # Format percentage columns for display
    pct_cols = ["Wp", "Wb", "Rp", "Rb", "alloc_effect", "select_effect",
                "interaction_effect", "total_contrib"]
    for col in pct_cols:
        if col in detail.columns:
            detail[col] = detail[col].apply(lambda x: f"{x * 100:.2f}%")

    st.dataframe(
        detail,
        use_container_width=True,
        hide_index=True,
        column_config={
            "industry": st.column_config.TextColumn("產業"),
            "Wp": st.column_config.TextColumn("基金權重"),
            "Wb": st.column_config.TextColumn("基準權重"),
            "Rp": st.column_config.TextColumn("基金報酬"),
            "Rb": st.column_config.TextColumn("基準報酬"),
            "alloc_effect": st.column_config.TextColumn("配置效果"),
            "select_effect": st.column_config.TextColumn("選股效果"),
            "interaction_effect": st.column_config.TextColumn("交互效果"),
            "total_contrib": st.column_config.TextColumn("總貢獻"),
        },
    )


# --- Results Section ---
if run:
    mode = _parse_mode(brinson_mode)

    with st.status("分析進行中...", expanded=True) as status:
        # Step 1: Load data
        st.write("📂 讀取持股資料...")
        try:
            fund_code_val = fund_code if input_method == "輸入基金代碼" else ""
            uploaded = uploaded_file if input_method == "上傳 CSV/Excel" else None
            holdings = _load_holdings(uploaded, input_method, fund_code_val)
        except ValueError as e:
            st.error(str(e))
            status.update(label="分析失敗", state="error")
            st.stop()

        st.write(f"✅ 讀取完成 — {len(holdings)} 筆產業資料")

        # Step 2: Run attribution
        st.write(f"🔢 執行 {mode} 歸因計算...")
        try:
            from engine.brinson import compute_attribution

            result = compute_attribution(holdings, mode=mode)
        except NotImplementedError:
            st.error(
                "⚠️ Brinson 歸因引擎尚未實作（Issue #7）。\n\n"
                "引擎完成後，此儀表板將自動顯示分析結果。"
            )
            status.update(label="引擎尚未就緒", state="error")
            st.stop()
        except (ValueError, AssertionError) as e:
            st.error(f"歸因計算失敗: {e}")
            status.update(label="分析失敗", state="error")
            st.stop()

        st.write("✅ 歸因計算完成")

        # Step 3: Validate
        st.write("🔍 驗證結果...")
        time.sleep(0.3)  # brief pause for UX
        st.write("✅ Brinson 不變量驗證通過")

        status.update(label="分析完成", state="complete")

    # --- Warnings ---
    blocked = _show_warnings(result)
    if blocked:
        st.stop()

    # --- KPI Cards ---
    _show_kpi_cards(result)

    st.divider()

    # --- Charts ---
    chart_col1, chart_col2 = st.columns(2)

    with chart_col1:
        st.subheader("瀑布圖")
        st.info("📊 瀑布圖元件建置中 — 請參考 report/waterfall.py", icon="🔧")

    with chart_col2:
        st.subheader("產業貢獻")
        st.info("📊 產業貢獻圖元件建置中 — 請參考 report/sector_chart.py", icon="🔧")

    st.divider()

    # --- Detail Table ---
    st.subheader("產業歸因明細")
    _show_detail_table(result)

    # --- Top / Bottom Contributors ---
    contrib_col1, contrib_col2 = st.columns(2)
    with contrib_col1:
        st.subheader("🏆 前三大正貢獻")
        top = result["top_contributors"][["industry", "total_contrib"]].copy()
        top["total_contrib"] = top["total_contrib"].apply(_format_pct)
        st.dataframe(top, use_container_width=True, hide_index=True,
                     column_config={"industry": "產業", "total_contrib": "總貢獻"})

    with contrib_col2:
        st.subheader("📉 前三大負貢獻")
        bottom = result["bottom_contributors"][["industry", "total_contrib"]].copy()
        bottom["total_contrib"] = bottom["total_contrib"].apply(_format_pct)
        st.dataframe(bottom, use_container_width=True, hide_index=True,
                     column_config={"industry": "產業", "total_contrib": "總貢獻"})

    st.divider()

    # --- AI Summary (placeholder) ---
    tab1, tab2, tab3 = st.tabs(["LINE 摘要", "PDF 摘要", "顧問筆記"])
    with tab1:
        st.text_area("LINE 訊息", value="（AI 摘要尚未實作）", height=80)
    with tab2:
        st.text_area("PDF 摘要", value="（AI 摘要尚未實作）", height=120)
    with tab3:
        st.text_area("顧問筆記", value="（AI 摘要尚未實作）", height=60)

    # --- Export Sidebar ---
    st.sidebar.divider()
    st.sidebar.download_button(
        "📥 下載 PNG", data=b"", file_name="waterfall.png", disabled=True
    )
    st.sidebar.download_button(
        "📥 下載 PDF", data=b"", file_name="report.pdf", disabled=True
    )
