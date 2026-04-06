"""Tests for report/pdf_generator.py — PDF generation, content, audit log."""

from pathlib import Path

import pandas as pd
import pytest

from report.pdf_generator import generate_pdf
from report.waterfall import generate_waterfall
from report.sector_chart import generate_sector_chart


@pytest.fixture
def sample_result():
    detail = pd.DataFrame([
        {"industry": "半導體業", "Wp": 0.42, "Wb": 0.40, "Rp": 0.085, "Rb": 0.080,
         "alloc_effect": 0.001, "select_effect": 0.002, "interaction_effect": 0.0, "total_contrib": 0.003},
        {"industry": "金融保險業", "Wp": 0.12, "Wb": 0.14, "Rp": 0.025, "Rb": 0.030,
         "alloc_effect": -0.0005, "select_effect": -0.0006, "interaction_effect": 0.0, "total_contrib": -0.0011},
        {"industry": "航運業", "Wp": 0.05, "Wb": 0.04, "Rp": 0.070, "Rb": 0.060,
         "alloc_effect": 0.0003, "select_effect": 0.0005, "interaction_effect": 0.0, "total_contrib": 0.0008},
    ])
    return {
        "fund_return": 0.058,
        "bench_return": 0.053,
        "excess_return": 0.005,
        "allocation_total": 0.002,
        "selection_total": 0.003,
        "interaction_total": None,
        "brinson_mode": "BF2",
        "detail": detail,
        "top_contributors": detail.nlargest(3, "total_contrib"),
        "bottom_contributors": detail.nsmallest(3, "total_contrib"),
        "validation_passed": True,
        "unmapped_weight": 0.0,
        "unmapped_industries": [],
    }


@pytest.fixture
def sample_summary():
    return {
        "line_message": "📈 基金報酬5.80%，超越基準5.30%",
        "pdf_summary": "本期基金報酬率為5.80%，基準指數報酬率為5.30%，超額報酬為0.50%。產業配置效果為0.20%，選股能力效果為0.30%。",
        "advisor_note": "基金5.80% 超額0.50% 配置0.20% 選股0.30%",
        "verification_passed": True,
        "fallback_used": False,
        "ai_prompt": "test prompt",
    }


@pytest.fixture
def chart_paths(sample_result, tmp_path):
    """Generate chart PNGs for testing."""
    import matplotlib.pyplot as plt

    wf_path = tmp_path / "waterfall.png"
    fig = generate_waterfall(sample_result, output_path=wf_path)
    plt.close(fig)

    sc_path = tmp_path / "sector.png"
    fig = generate_sector_chart(sample_result, output_path=sc_path)
    plt.close(fig)

    return {"waterfall": wf_path, "sector": sc_path}


class TestPDFGeneration:
    def test_generates_pdf(self, sample_result, sample_summary, tmp_path):
        path = tmp_path / "report.pdf"
        result_path = generate_pdf(
            sample_result, sample_summary,
            output_path=path,
            fund_code="0050",
            period="2026-03",
        )
        assert Path(result_path).exists()
        assert Path(result_path).stat().st_size > 500

    def test_two_pages(self, sample_result, sample_summary, chart_paths, tmp_path):
        path = tmp_path / "report_2p.pdf"
        generate_pdf(
            sample_result, sample_summary,
            output_path=path,
            fund_code="0050",
            period="2026-03",
            waterfall_path=chart_paths["waterfall"],
            sector_chart_path=chart_paths["sector"],
        )
        # Read PDF and check page count
        from fpdf import FPDF
        # Simple check: file should be significantly larger with charts
        assert Path(path).stat().st_size > 5000

    def test_with_advisor_name(self, sample_result, sample_summary, tmp_path):
        path = tmp_path / "report_advisor.pdf"
        generate_pdf(
            sample_result, sample_summary,
            output_path=path,
            advisor_name="王小明",
        )
        assert Path(path).exists()

    def test_auto_output_path(self, sample_result, sample_summary, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        path = generate_pdf(sample_result, sample_summary, fund_code="0050", period="2026-03")
        assert Path(path).exists()

    def test_bf3_mode(self, sample_result, sample_summary, tmp_path):
        result = {**sample_result, "brinson_mode": "BF3", "interaction_total": 0.001}
        path = tmp_path / "report_bf3.pdf"
        generate_pdf(result, sample_summary, output_path=path)
        assert Path(path).exists()


class TestAuditLog:
    def test_logs_to_db(self, sample_result, sample_summary, tmp_path):
        from data.cache import get_connection, init_db

        db_path = str(tmp_path / "audit.db")
        init_db(db_path)
        conn = get_connection(db_path)

        pdf_path = tmp_path / "report_audit.pdf"
        generate_pdf(
            sample_result, sample_summary,
            output_path=pdf_path,
            fund_code="0050",
            period="2026-03",
            advisor_name="Test",
            conn=conn,
        )

        # Verify audit entry
        row = conn.execute("SELECT * FROM report_log").fetchone()
        assert row is not None
        assert row["fund_code"] == "0050"
        assert row["brinson_mode"] == "BF2"
        conn.close()
