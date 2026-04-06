"""PDF report generator using fpdf2.

2-page A4 layout, 20mm margins:
  Page 1: Title + KPIs + Narrative + Waterfall chart
  Page 2: Sector chart + Detail table + Disclaimer

CJK support via system CJK font (STHeiti / PingFang / Hiragino).
"""

import logging
import tempfile
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from fpdf import FPDF

from config.settings import CHART_DPI

logger = logging.getLogger(__name__)

# CJK font candidates (TTC/TTF paths on macOS/Linux)
_CJK_FONT_PATHS = [
    "/System/Library/Fonts/STHeiti Medium.ttc",
    "/System/Library/Fonts/PingFang.ttc",
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc",
]

MARGIN = 20  # mm
DISCLAIMER = (
    "免責聲明：本報告僅供參考，不構成投資建議。過去績效不代表未來表現。"
    "歸因分析結果基於所提供之持股資料與市場指數，實際結果可能因資料來源差異而有所不同。"
)


def _find_cjk_font() -> Optional[str]:
    """Find a CJK font path on the system."""
    for path in _CJK_FONT_PATHS:
        if Path(path).exists():
            return path
    return None


def _fmt_pct(value: float) -> str:
    return f"{value * 100:.2f}%"


def generate_pdf(
    result: dict,
    summary: dict,
    output_path: Optional[str | Path] = None,
    fund_code: str = "",
    period: str = "",
    advisor_name: str = "",
    waterfall_path: Optional[str | Path] = None,
    sector_chart_path: Optional[str | Path] = None,
    conn=None,
) -> str:
    """Generate a 2-page PDF report.

    Args:
        result: AttributionResult dict.
        summary: AISummary dict (or fallback).
        output_path: Where to save the PDF. Auto-generated if None.
        fund_code: Fund code for title.
        period: Analysis period.
        advisor_name: Advisor name for branding.
        waterfall_path: Path to waterfall chart PNG.
        sector_chart_path: Path to sector chart PNG.
        conn: SQLite connection for audit logging.

    Returns:
        Path to the generated PDF file.
    """
    if output_path is None:
        output_path = f"output/report_{fund_code}_{period}_{datetime.now().strftime('%Y%m%d%H%M%S')}.pdf"

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    pdf = FPDF(orientation="P", unit="mm", format="A4")
    pdf.set_auto_page_break(auto=True, margin=MARGIN)

    # Load CJK font
    font_path = _find_cjk_font()
    if font_path:
        pdf.add_font("CJK", "", font_path)
        pdf.add_font("CJK", "B", font_path)
        font_name = "CJK"
    else:
        font_name = "Helvetica"
        logger.warning("No CJK font found — falling back to Helvetica (Chinese may not render)")

    # ================================================================
    # Page 1: Title + KPIs + AI Narrative + Waterfall Chart
    # ================================================================
    pdf.add_page()
    pdf.set_margins(MARGIN, MARGIN, MARGIN)

    # Title
    pdf.set_font(font_name, "B", 18)
    title = f"基金歸因分析報告"
    pdf.cell(0, 12, title, new_x="LMARGIN", new_y="NEXT", align="C")

    # Subtitle
    pdf.set_font(font_name, "", 11)
    subtitle_parts = []
    if fund_code:
        subtitle_parts.append(fund_code)
    if period:
        subtitle_parts.append(period)
    if advisor_name:
        subtitle_parts.append(f"顧問：{advisor_name}")
    if subtitle_parts:
        pdf.cell(0, 8, " | ".join(subtitle_parts), new_x="LMARGIN", new_y="NEXT", align="C")

    pdf.ln(5)

    # KPI boxes
    pdf.set_font(font_name, "B", 10)
    mode = result.get("brinson_mode", "BF2")
    kpis = [
        ("基金報酬", _fmt_pct(result["fund_return"])),
        ("基準報酬", _fmt_pct(result["bench_return"])),
        ("超額報酬", _fmt_pct(result["excess_return"])),
        ("產業配置", _fmt_pct(result["allocation_total"])),
        ("選股能力", _fmt_pct(result["selection_total"])),
    ]
    if mode == "BF3" and result.get("interaction_total") is not None:
        kpis.append(("交互效果", _fmt_pct(result["interaction_total"])))

    col_width = (210 - 2 * MARGIN) / len(kpis)
    for label, value in kpis:
        pdf.cell(col_width, 6, label, align="C")
    pdf.ln()
    pdf.set_font(font_name, "B", 13)
    for label, value in kpis:
        pdf.cell(col_width, 8, value, align="C")
    pdf.ln(10)

    # AI Narrative
    pdf.set_font(font_name, "B", 11)
    pdf.cell(0, 7, "分析摘要", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font(font_name, "", 10)
    pdf_text = summary.get("pdf_summary", "")
    pdf.multi_cell(0, 6, pdf_text)
    pdf.ln(5)

    # Waterfall chart
    if waterfall_path and Path(waterfall_path).exists():
        img_width = 210 - 2 * MARGIN
        pdf.image(str(waterfall_path), x=MARGIN, w=img_width)

    # ================================================================
    # Page 2: Sector Chart + Detail Table + Disclaimer
    # ================================================================
    pdf.add_page()

    # Sector chart
    if sector_chart_path and Path(sector_chart_path).exists():
        img_width = 210 - 2 * MARGIN
        pdf.image(str(sector_chart_path), x=MARGIN, w=img_width)
        pdf.ln(5)

    # Detail table
    detail = result.get("detail")
    if detail is not None and len(detail) > 0:
        pdf.set_font(font_name, "B", 11)
        pdf.cell(0, 7, "產業明細", new_x="LMARGIN", new_y="NEXT")
        pdf.ln(2)

        # Table header
        headers = ["產業", "基金權重", "基準權重", "配置效果", "選股效果", "總貢獻"]
        col_widths = [40, 22, 22, 25, 25, 25]

        pdf.set_font(font_name, "B", 8)
        for h, w in zip(headers, col_widths):
            pdf.cell(w, 6, h, border=1, align="C")
        pdf.ln()

        # Table rows
        pdf.set_font(font_name, "", 8)
        for _, row in detail.iterrows():
            pdf.cell(col_widths[0], 5, str(row["industry"])[:10], border=1)
            pdf.cell(col_widths[1], 5, _fmt_pct(row["Wp"]), border=1, align="R")
            pdf.cell(col_widths[2], 5, _fmt_pct(row["Wb"]), border=1, align="R")
            pdf.cell(col_widths[3], 5, _fmt_pct(row["alloc_effect"]), border=1, align="R")
            pdf.cell(col_widths[4], 5, _fmt_pct(row["select_effect"]), border=1, align="R")
            pdf.cell(col_widths[5], 5, _fmt_pct(row["total_contrib"]), border=1, align="R")
            pdf.ln()

    # Disclaimer
    pdf.ln(10)
    pdf.set_font(font_name, "", 7)
    pdf.set_text_color(128, 128, 128)
    pdf.multi_cell(0, 4, DISCLAIMER)
    pdf.set_text_color(0, 0, 0)

    # Footer with generation info
    pdf.set_font(font_name, "", 6)
    pdf.set_text_color(180, 180, 180)
    gen_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    pdf.cell(0, 4, f"Generated: {gen_time} | Mode: {mode}", new_x="LMARGIN", new_y="NEXT", align="R")

    # Save
    pdf.output(str(output_path))
    logger.info("PDF saved: %s", output_path)

    # Audit log
    if conn is not None:
        from data.cache import log_report
        report_id = str(uuid.uuid4())[:8]
        log_report(
            conn,
            report_id=report_id,
            fund_code=fund_code,
            period=period,
            brinson_mode=mode,
            advisor_name=advisor_name,
            pdf_path=str(output_path),
        )
        logger.info("Report logged: %s", report_id)

    return str(output_path)
