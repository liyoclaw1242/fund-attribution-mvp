"""Fund Attribution Analysis MVP — Streamlit Application.

基金歸因分析系統
Target: Professional Financial Advisors in Taiwan

End-to-end flow: 輸入 → 計算 → 驗證 → 圖表 → AI 摘要 → 匯出
"""

import io
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

# --- Sidebar ---
st.sidebar.header("顧問資訊")
advisor_name = st.sidebar.text_input("理財顧問姓名", help="將顯示於 PDF 報告封面")
advisor_branch = st.sidebar.text_input("所屬分行", help="將顯示於 PDF 報告")

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

run = st.button("🚀 開始分析", type="primary", use_container_width=True)


# --- Helper Functions ---

def _parse_mode(label: str) -> str:
    """Extract mode string from radio label."""
    return "BF3" if "BF3" in label else "BF2"


def _load_holdings(uploaded_file, input_method: str, fund_code: str = "") -> pd.DataFrame:
    """Load holdings DataFrame from uploaded file or fund code.

    Returns DataFrame with columns [industry, Wp, Wb, Rp, Rb].
    """
    if input_method == "上傳 CSV/Excel":
        if uploaded_file is None:
            raise ValueError("請先上傳持股資料檔案")

        if uploaded_file.name.endswith(".csv"):
            df = pd.read_csv(uploaded_file)
        else:
            df = pd.read_excel(uploaded_file)

        required = ["industry", "Wp", "Wb", "Rp", "Rb"]
        if all(c in df.columns for c in required):
            return df[required]

        raise ValueError(
            "上傳的檔案缺少基準資料（Wb, Rb 欄位）。\n"
            "請使用包含 industry, Wp, Wb, Rp, Rb 欄位的完整資料集，"
            "或改用「輸入基金代碼」模式自動取得基準。"
        )
    else:
        if not fund_code.strip():
            raise ValueError("請輸入基金代碼")
        from data.fund_lookup import lookup_fund
        return lookup_fund(fund_code.strip())


def _format_pct(value: float) -> str:
    """Format a decimal as signed percentage string."""
    return f"{value * 100:+.2f}%"


def _run_validation(holdings: pd.DataFrame, result: dict) -> list:
    """Run validation and return results. Returns empty list if validator unavailable."""
    try:
        from engine.validator import validate_all
        return validate_all(
            holdings,
            attribution_result=result,
            unmapped_weight=result["unmapped_weight"],
        )
    except (NotImplementedError, ImportError):
        return []


def _show_validation_warnings(validation_results: list) -> bool:
    """Display validation warnings/blockers. Returns True if blocked."""
    blocked = False
    for vr in validation_results:
        if vr.level == "block":
            st.error(f"🚫 驗證失敗 [{vr.rule}]: {vr.message}", icon="🚫")
            blocked = True
        elif vr.level == "warn":
            st.warning(f"⚠️ 驗證警告 [{vr.rule}]: {vr.message}", icon="⚠️")
    return blocked


def _show_unmapped_warnings(result: dict) -> bool:
    """Display unmapped weight warnings. Returns True if blocked."""
    unmapped = result["unmapped_weight"]
    if unmapped >= UNMAPPED_BLOCK_THRESHOLD:
        st.error(
            f"🚫 未對照產業權重 {unmapped * 100:.1f}% 超過 {UNMAPPED_BLOCK_THRESHOLD * 100:.0f}% 門檻 — "
            f"分析結果不可靠，已阻擋顯示。\n\n"
            f"未對照: {', '.join(result['unmapped_industries']) or '(none)'}",
            icon="🚫",
        )
        return True
    if unmapped >= UNMAPPED_WARN_THRESHOLD:
        st.warning(
            f"⚠️ 未對照產業權重 {unmapped * 100:.1f}% 超過 {UNMAPPED_WARN_THRESHOLD * 100:.0f}% 警戒 — "
            f"結果僅供參考。\n\n"
            f"未對照: {', '.join(result['unmapped_industries']) or '(none)'}",
            icon="⚠️",
        )
    return False


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


def _render_waterfall(result: dict) -> bytes | None:
    """Render waterfall chart. Returns PNG bytes or None if unavailable."""
    try:
        from report.waterfall import generate_waterfall
        fig = generate_waterfall(result)
        buf = io.BytesIO()
        fig.savefig(buf, format="png", bbox_inches="tight")
        import matplotlib.pyplot as plt
        plt.close(fig)
        return buf.getvalue()
    except (NotImplementedError, ImportError):
        return None


def _render_sector_chart(result: dict) -> bytes | None:
    """Render sector contribution chart. Returns PNG bytes or None."""
    try:
        from report.sector_chart import generate_sector_chart
        fig = generate_sector_chart(result)
        buf = io.BytesIO()
        fig.savefig(buf, format="png", bbox_inches="tight")
        import matplotlib.pyplot as plt
        plt.close(fig)
        return buf.getvalue()
    except (NotImplementedError, ImportError):
        return None


def _generate_ai_summary(result: dict) -> dict | None:
    """Generate AI summary. Returns AISummary dict or None."""
    try:
        from ai.claude_client import generate_summary
        return generate_summary(result)
    except (NotImplementedError, ImportError):
        return None


def _generate_fallback_summary(result: dict) -> dict | None:
    """Generate rule-based fallback summary."""
    try:
        from ai.fallback_template import generate_fallback
        return generate_fallback(result)
    except (NotImplementedError, ImportError):
        return None


def _generate_pdf(
    result: dict,
    waterfall_png: bytes | None,
    sector_png: bytes | None,
    ai_summary: dict | None,
    advisor_name: str = "",
    advisor_branch: str = "",
) -> bytes | None:
    """Generate PDF report. Returns PDF bytes or None."""
    try:
        import tempfile
        from pathlib import Path
        from report.pdf_generator import generate_pdf

        waterfall_path = None
        sector_path = None
        tmp_files = []

        # Write PNG bytes to temp files for pdf_generator
        if waterfall_png:
            tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
            tmp.write(waterfall_png)
            tmp.close()
            waterfall_path = tmp.name
            tmp_files.append(tmp.name)

        if sector_png:
            tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
            tmp.write(sector_png)
            tmp.close()
            sector_path = tmp.name
            tmp_files.append(tmp.name)

        pdf_path = generate_pdf(
            result,
            summary=ai_summary or {},
            advisor_name=advisor_name,
            waterfall_path=waterfall_path,
            sector_chart_path=sector_path,
        )

        pdf_bytes = Path(pdf_path).read_bytes()

        # Cleanup temp files
        import os
        for f in tmp_files:
            os.unlink(f)

        return pdf_bytes
    except (NotImplementedError, ImportError):
        return None


def _show_detail_table(result: dict):
    """Display the industry detail breakdown table."""
    detail = result["detail"].copy()
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

    # Collect outputs for export
    waterfall_png = None
    sector_png = None
    ai_summary = None
    pdf_bytes = None

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
        validation_results = _run_validation(holdings, result)
        if validation_results:
            st.write(f"✅ 驗證完成 — {len(validation_results)} 項規則")
        else:
            st.write("⏭️ 驗證模組尚未就緒，跳過")

        # Step 4: Generate charts
        st.write("📊 產生圖表...")
        waterfall_png = _render_waterfall(result)
        sector_png = _render_sector_chart(result)
        if waterfall_png and sector_png:
            st.write("✅ 圖表產生完成")
        else:
            st.write("⏭️ 圖表模組建置中（Issue #11）")

        # Step 5: Generate AI summary
        st.write("🤖 產生 AI 摘要...")
        ai_summary = _generate_ai_summary(result)
        fallback_used = False
        if ai_summary is None:
            ai_summary = _generate_fallback_summary(result)
            if ai_summary is not None:
                fallback_used = True
                st.write("⚠️ AI 摘要不可用，已使用規則模板")
            else:
                st.write("⏭️ AI 摘要模組建置中（Issue #10）")

        if ai_summary and not fallback_used:
            if ai_summary.get("fallback_used"):
                fallback_used = True
                st.write("⚠️ AI 數字驗證失敗，已使用規則模板替代")
            else:
                st.write("✅ AI 摘要產生完成")

        # Step 6: Generate PDF
        st.write("📄 產生 PDF 報告...")
        pdf_bytes = _generate_pdf(
            result, waterfall_png, sector_png, ai_summary,
            advisor_name=advisor_name, advisor_branch=advisor_branch,
        )
        if pdf_bytes:
            st.write("✅ PDF 報告產生完成")
        else:
            st.write("⏭️ PDF 模組建置中（Issue #12）")

        status.update(label="分析完成", state="complete")

    # --- Validation Warnings ---
    blocked = False
    if validation_results:
        blocked = _show_validation_warnings(validation_results)
    if not blocked:
        blocked = _show_unmapped_warnings(result)
    if blocked:
        st.stop()

    # --- AI Fallback Warning ---
    if fallback_used:
        st.warning("🤖 AI 摘要產生失敗，已使用規則模板替代。數字準確但語句較為制式。", icon="🤖")

    # --- KPI Cards ---
    _show_kpi_cards(result)

    st.divider()

    # --- Charts ---
    chart_col1, chart_col2 = st.columns(2)

    with chart_col1:
        st.subheader("瀑布圖")
        if waterfall_png:
            st.image(waterfall_png, use_container_width=True)
        else:
            st.info("📊 瀑布圖元件建置中 — 請參考 report/waterfall.py", icon="🔧")

    with chart_col2:
        st.subheader("產業貢獻")
        if sector_png:
            st.image(sector_png, use_container_width=True)
        else:
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

    # --- AI Summary Tabs ---
    st.subheader("AI 分析摘要")
    tab1, tab2, tab3 = st.tabs(["LINE 摘要", "PDF 摘要", "顧問筆記"])

    line_text = ai_summary.get("line_message", "") if ai_summary else ""
    pdf_text = ai_summary.get("pdf_summary", "") if ai_summary else ""
    advisor_note = ai_summary.get("advisor_note", "") if ai_summary else ""

    with tab1:
        st.text_area(
            "LINE 訊息",
            value=line_text or "（AI 摘要模組建置中）",
            height=80,
            disabled=not line_text,
        )
    with tab2:
        st.text_area(
            "PDF 摘要",
            value=pdf_text or "（AI 摘要模組建置中）",
            height=120,
            disabled=not pdf_text,
        )
    with tab3:
        st.text_area(
            "顧問筆記",
            value=advisor_note or "（AI 摘要模組建置中）",
            height=60,
            disabled=not advisor_note,
        )

    # --- Export Sidebar ---
    st.sidebar.divider()
    st.sidebar.header("匯出")

    if waterfall_png:
        st.sidebar.download_button(
            "📥 下載 PNG（瀑布圖）",
            data=waterfall_png,
            file_name="waterfall.png",
            mime="image/png",
        )
    else:
        st.sidebar.download_button(
            "📥 下載 PNG", data=b"", file_name="waterfall.png", disabled=True
        )

    if pdf_bytes:
        st.sidebar.download_button(
            "📥 下載 PDF 報告",
            data=pdf_bytes,
            file_name="fund_attribution_report.pdf",
            mime="application/pdf",
        )
    else:
        st.sidebar.download_button(
            "📥 下載 PDF", data=b"", file_name="report.pdf", disabled=True
        )

    if line_text:
        st.sidebar.code(line_text, language=None)
        st.sidebar.caption("👆 選取上方文字可複製 LINE 訊息")
    else:
        st.sidebar.caption("LINE 文字複製功能待 AI 摘要模組完成")
