"""v2.0 Advisor Dashboard — 顧問儀表板

Morning Briefing + Anomaly Alerts + Crisis Response + Fund Comparator + Health Check.
Each section uses deferred imports with graceful fallback when backend is unavailable.
"""

import streamlit as st

st.set_page_config(
    page_title="顧問儀表板",
    page_icon="🧠",
    layout="wide",
)

st.title("🧠 顧問儀表板 v2.0")
st.caption("Advisor Dashboard — 每日晨報、異常偵測、恐慌應對、基金比較、健康檢查")


# --- API client helper ---
def _api_available() -> bool:
    """Check if the FastAPI service is reachable."""
    try:
        from utils.api_client import check_health
        check_health()
        return True
    except Exception:
        return False


# --- Severity badge ---
SEVERITY_COLORS = {
    "critical": "#E24B4A",
    "warning": "#BA7517",
    "info": "#378ADD",
}


def _severity_badge(severity: str) -> str:
    color = SEVERITY_COLORS.get(severity, "#888")
    label = {"critical": "嚴重", "warning": "警告", "info": "資訊"}.get(severity, severity)
    return (
        f'<span style="display:inline-block;padding:2px 8px;border-radius:12px;'
        f'background:{color}20;color:{color};font-size:12px;font-weight:600;">'
        f'{label}</span>'
    )


# ===================================================================
# Tab navigation
# ===================================================================

tab_briefing, tab_anomaly, tab_crisis, tab_comparator, tab_health = st.tabs([
    "📋 每日晨報",
    "🔔 異常警示",
    "🚨 恐慌應對",
    "⚖️ 基金比較",
    "🩺 健康檢查",
])


# ===================================================================
# 1. Morning Briefing (F-203)
# ===================================================================

with tab_briefing:
    st.subheader("📋 每日晨報")
    st.caption("Morning Briefing — 今日重點警示與建議話術")

    def _load_briefing():
        """Load or generate morning briefing via API.

        Note: No dedicated briefing API endpoint yet — returns None
        to show the fallback "module building" message.
        """
        return None

    briefing = _load_briefing()

    if briefing is None:
        st.info(
            "📋 每日晨報模組建置中 — 後端完成後將自動顯示。\n\n"
            "功能預覽：每日自動掃描客戶持股異常，產生前 3 大警示與建議話術。",
            icon="🔧",
        )
    else:
        if briefing.summary:
            st.markdown(f"**摘要：** {briefing.summary}")

        if not briefing.items:
            st.success("✅ 今日無重大警示 — 所有客戶持股正常。")
        else:
            for i, item in enumerate(briefing.items):
                with st.container():
                    col_badge, col_content = st.columns([1, 5])
                    with col_badge:
                        st.markdown(
                            _severity_badge(item.severity),
                            unsafe_allow_html=True,
                        )
                        st.caption(item.signal_type)
                    with col_content:
                        st.markdown(f"**建議動作：** {item.suggested_action}")
                        st.caption(
                            f"影響客戶：{', '.join(item.affected_clients)}"
                        )

                        with st.expander("💬 建議話術"):
                            st.markdown(item.talking_points)

                    if i < len(briefing.items) - 1:
                        st.divider()


# ===================================================================
# 2. Anomaly Alerts (F-202)
# ===================================================================

with tab_anomaly:
    st.subheader("🔔 異常警示")
    st.caption("Anomaly Alerts — 客戶持股異常訊號監控")

    def _load_alerts():
        """Scan all clients for anomalies via API.

        Note: No dedicated anomaly API endpoint yet — returns None
        to show the fallback "module building" message.
        """
        return None

    alerts = _load_alerts()

    if alerts is None:
        st.info(
            "🔔 異常偵測模組建置中 — 後端完成後將自動顯示。\n\n"
            "功能預覽：掃描 6 大警訊（PE 百分位、RSI 超買、資金流出、外資賣超、集中度過高、風格漂移）。",
            icon="🔧",
        )
    else:
        # Filters
        filter_col1, filter_col2, _ = st.columns([1, 1, 2])
        with filter_col1:
            severity_filter = st.multiselect(
                "嚴重度篩選",
                options=["critical", "warning", "info"],
                default=["critical", "warning", "info"],
                format_func=lambda x: {"critical": "嚴重", "warning": "警告", "info": "資訊"}.get(x, x),
            )
        with filter_col2:
            signal_types = sorted(set(a.signal_type for a in alerts)) if alerts else []
            signal_filter = st.multiselect(
                "訊號類型篩選",
                options=signal_types,
                default=signal_types,
            )

        filtered = [
            a for a in alerts
            if a.severity in severity_filter and a.signal_type in signal_filter
        ]

        if not filtered:
            st.success("✅ 目前無異常警示。")
        else:
            st.caption(f"共 {len(filtered)} 筆警示")

            # Build table data
            import pandas as pd
            alert_data = []
            for a in filtered:
                alert_data.append({
                    "客戶": a.client_id,
                    "基金": a.fund_code,
                    "訊號類型": a.signal_type,
                    "嚴重度": a.severity,
                    "數值": f"{a.value:.2f}",
                    "門檻": f"{a.threshold:.2f}",
                    "說明": a.message,
                })

            df = pd.DataFrame(alert_data)
            st.dataframe(
                df,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "嚴重度": st.column_config.TextColumn(
                        "嚴重度",
                        help="critical=嚴重, warning=警告, info=資訊",
                    ),
                },
            )

            # Acknowledge buttons
            st.divider()
            st.caption("確認處理")
            ack_cols = st.columns(min(len(filtered), 4))
            for i, a in enumerate(filtered[:4]):
                with ack_cols[i]:
                    if st.button(
                        f"✅ 確認 {a.client_id}/{a.fund_code}",
                        key=f"ack_{a.client_id}_{a.fund_code}_{a.signal_type}",
                    ):
                        # Acknowledge API endpoint not yet available
                        st.warning("確認功能尚未完全就緒")


# ===================================================================
# 3. Crisis Response (F-206)
# ===================================================================

with tab_crisis:
    st.subheader("🚨 恐慌應對")
    st.caption("Crisis Response — 市場大跌時的客戶安撫機制")

    def _check_crisis():
        """Check for crisis trigger via API.

        Note: No dedicated crisis API endpoint yet — returns None
        to show the fallback "module building" message.
        """
        return None, None

    crisis_status, crisis_report = _check_crisis()

    if crisis_status is None:
        st.info(
            "🚨 恐慌應對模組建置中 — 後端完成後將自動顯示。\n\n"
            "功能預覽：偵測大盤跌幅 >3% 時自動觸發，列出受影響客戶並產生安撫話術。",
            icon="🔧",
        )
    elif crisis_status is False:
        st.success("✅ 目前市場正常 — 未觸發恐慌應對機制。")
        st.caption("當大盤單日跌幅超過 3% 時，系統將自動啟動恐慌應對。")
    else:
        # Crisis triggered
        report = crisis_report

        # Banner
        st.error(
            f"⚠️ 市場大跌警報 — 大盤跌幅 {report.market_drop_pct * 100:.1f}%"
            f"（{report.trigger_date}）",
            icon="🚨",
        )

        # General talking points
        if report.talking_points:
            with st.expander("💬 通用安撫話術", expanded=True):
                st.markdown(report.talking_points)

        # Historical comparisons
        if report.historical_comparisons:
            st.subheader("📊 歷史事件對照")
            import pandas as pd
            hist_data = []
            for comp in report.historical_comparisons:
                hist_data.append({
                    "事件": comp.get("event", ""),
                    "日期": comp.get("date", ""),
                    "跌幅": comp.get("drop", ""),
                    "恢復時間": comp.get("recovery", ""),
                })
            if hist_data:
                st.dataframe(
                    pd.DataFrame(hist_data),
                    use_container_width=True,
                    hide_index=True,
                )

        # Affected clients
        if report.affected_clients:
            st.subheader("👥 受影響客戶")

            for client in report.affected_clients:
                with st.container():
                    c1, c2, c3 = st.columns([2, 1, 1])
                    with c1:
                        st.markdown(f"**{client.name}**（{client.client_id}）")
                    with c2:
                        st.metric(
                            "曝險比例",
                            f"{client.exposure_pct * 100:.1f}%",
                        )
                    with c3:
                        st.metric(
                            "預估損失",
                            f"${client.estimated_loss:,.0f}",
                            delta=f"-${client.estimated_loss:,.0f}",
                            delta_color="inverse",
                        )

                    with st.expander(f"💬 {client.name} 專屬話術"):
                        st.markdown(client.talking_point)

                    st.divider()


# ===================================================================
# 4. Fund Comparator (F-204)
# ===================================================================

with tab_comparator:
    st.subheader("⚖️ 基金比較")
    st.caption("Fund Comparator — 選擇 2-4 檔基金進行並排比較")

    # Fund selection
    fund_input = st.text_input(
        "輸入基金代碼（以逗號分隔，2-4 檔）",
        placeholder="例如：0050, 0056, 00878",
        help="輸入 2 到 4 個基金代碼",
    )

    # File upload for holdings data
    holdings_file = st.file_uploader(
        "上傳基金持股資料",
        type=["csv", "xlsx"],
        help="欄位需包含：fund_code, industry, Wp, Wb, Rp, Rb",
        key="comparator_upload",
    )

    compare_btn = st.button("🔍 開始比較", type="primary", use_container_width=True)

    if compare_btn and fund_input.strip():
        fund_codes = [f.strip() for f in fund_input.split(",") if f.strip()]

        if len(fund_codes) < 2:
            st.error("請至少輸入 2 檔基金代碼。")
        elif len(fund_codes) > 4:
            st.error("最多比較 4 檔基金。")
        else:
            # Parse holdings if uploaded
            import pandas as pd
            holdings_map = {}
            if holdings_file is not None:
                try:
                    if holdings_file.name.endswith(".csv"):
                        df_all = pd.read_csv(holdings_file)
                    else:
                        df_all = pd.read_excel(holdings_file)

                    if "fund_code" in df_all.columns:
                        for code in fund_codes:
                            fund_df = df_all[df_all["fund_code"] == code]
                            if not fund_df.empty:
                                holdings_map[code] = fund_df
                except Exception as e:
                    st.error(f"持股資料解析錯誤：{e}")

            with st.spinner("比較分析中..."):
                try:
                    from engine.fund_comparator import compare_funds
                    result = compare_funds(
                        fund_codes=fund_codes,
                        holdings_map=holdings_map,
                        generate_ai=False,
                    )

                    # Metrics table
                    st.subheader("📊 指標比較")
                    metrics_data = []
                    for fm in result.funds:
                        row = {
                            "基金": fm.fund_code,
                            "總報酬": f"{fm.total_return * 100:.2f}%" if fm.total_return else "N/A",
                            "夏普比率": f"{fm.sharpe_ratio:.2f}" if fm.sharpe_ratio is not None else "N/A",
                            "最大回撤": f"{fm.max_drawdown * 100:.2f}%" if fm.max_drawdown is not None else "N/A",
                        }
                        metrics_data.append(row)

                    st.dataframe(
                        pd.DataFrame(metrics_data),
                        use_container_width=True,
                        hide_index=True,
                    )

                    # Sector allocation comparison chart
                    all_sectors = set()
                    for fm in result.funds:
                        all_sectors.update(fm.sector_weights.keys())

                    if all_sectors:
                        st.subheader("🏭 產業配置比較")
                        import matplotlib
                        matplotlib.use("Agg")
                        import matplotlib.pyplot as plt
                        import numpy as np

                        # CJK font detection (same pattern as other charts)
                        from matplotlib import font_manager
                        cjk_fonts = [
                            "Noto Sans CJK TC", "Noto Sans TC",
                            "PingFang TC", "Microsoft JhengHei",
                            "Heiti TC", "Source Han Sans TC",
                        ]
                        for fname in cjk_fonts:
                            matches = font_manager.findSystemFonts(
                                fontpaths=None, fontext="ttf"
                            )
                            if any(fname.lower().replace(" ", "") in m.lower() for m in matches):
                                plt.rcParams["font.family"] = fname
                                break

                        sectors = sorted(all_sectors)
                        x = np.arange(len(sectors))
                        width = 0.8 / len(result.funds)

                        fig, ax = plt.subplots(figsize=(12, 5))
                        colors = ["#378ADD", "#1D9E75", "#BA7517", "#534AB7"]

                        for i, fm in enumerate(result.funds):
                            values = [fm.sector_weights.get(s, 0) * 100 for s in sectors]
                            ax.bar(
                                x + i * width - 0.4 + width / 2,
                                values,
                                width,
                                label=fm.fund_code,
                                color=colors[i % len(colors)],
                                alpha=0.85,
                            )

                        ax.set_ylabel("配置比例 (%)")
                        ax.set_xticks(x)
                        ax.set_xticklabels(sectors, rotation=45, ha="right")
                        ax.legend()
                        ax.set_title("產業配置比較")
                        fig.tight_layout()

                        st.pyplot(fig, use_container_width=True)
                        plt.close(fig)

                    # AI explanation
                    if result.ai_explanation:
                        st.subheader("🤖 AI 比較分析")
                        st.markdown(result.ai_explanation)

                except (ImportError, NotImplementedError):
                    st.info(
                        "⚖️ 基金比較引擎建置中 — 後端完成後將自動啟用。",
                        icon="🔧",
                    )
                except Exception as e:
                    st.error(f"比較分析失敗：{e}")

    elif not fund_input.strip():
        st.caption("請在上方輸入基金代碼以開始比較。")


# ===================================================================
# 5. Health Check (F-205)
# ===================================================================

with tab_health:
    st.subheader("🩺 投資組合健康檢查")
    st.caption("Portfolio Health Check — 跨行持股彙整與風險診斷")

    # Client selector
    def _load_clients():
        """Load client list via FastAPI."""
        try:
            from utils.api_client import list_clients
            return list_clients()
        except Exception:
            return []

    clients = _load_clients()

    if not clients:
        # Manual input fallback
        client_id_input = st.text_input(
            "客戶 ID",
            placeholder="輸入客戶編號",
            help="尚無客戶資料 — 手動輸入客戶 ID 進行檢查",
        )
        selected_client_id = client_id_input.strip() if client_id_input else None
        selected_client_name = client_id_input.strip() if client_id_input else None
    else:
        client_options = {c["client_id"]: f"{c['name']}（{c['client_id']}）" for c in clients}
        selected = st.selectbox(
            "選擇客戶",
            options=list(client_options.keys()),
            format_func=lambda x: client_options[x],
        )
        selected_client_id = selected
        selected_client_name = next(
            (c["name"] for c in clients if c["client_id"] == selected), selected
        )

    check_btn = st.button("🩺 開始檢查", type="primary", use_container_width=True)

    if check_btn and selected_client_id:
        with st.spinner("健康檢查中..."):
            try:
                from utils.api_client import get_portfolio, APIUnavailableError
                portfolio = get_portfolio(selected_client_id)

                # Header
                st.markdown(f"### {selected_client_name} 的投資組合")

                # Cross-bank aggregation from API portfolio data
                holdings = portfolio.get("holdings", [])
                if holdings:
                    import pandas as pd
                    bank_breakdown = {}
                    for h in holdings:
                        bank = h.get("bank_name", "未知")
                        value = h.get("shares", 0) * h.get("cost_basis", 0)
                        bank_breakdown[bank] = bank_breakdown.get(bank, 0) + value

                    if bank_breakdown:
                        st.subheader("🏦 跨行持股彙整")
                        bank_data = [
                            {"銀行": bank, "市值 (TWD)": f"${value:,.0f}"}
                            for bank, value in bank_breakdown.items()
                        ]
                        st.dataframe(
                            pd.DataFrame(bank_data),
                            use_container_width=True,
                            hide_index=True,
                        )
                        total_value = sum(bank_breakdown.values())
                        st.metric("總資產", f"${total_value:,.0f}")

                    st.info(
                        "🩺 進階健康檢查（風險診斷、集中度分析）建置中 — "
                        "後端 API 完成後將自動啟用。",
                        icon="🔧",
                    )
                else:
                    st.info("此客戶目前無持股資料。")

            except ImportError:
                st.info(
                    "🩺 健康檢查模組建置中 — 後端完成後將自動啟用。",
                    icon="🔧",
                )
            except Exception as e:
                st.error(f"健康檢查失敗：{e}")

    elif check_btn and not selected_client_id:
        st.warning("請先選擇或輸入客戶。")
