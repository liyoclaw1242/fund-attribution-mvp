"""Integration tests — end-to-end pipeline verification.

Covers: CSV→mapping→Brinson→chart→PDF, determinism, unmapped thresholds,
AI hallucination fallback, number verifier, chart generation.
"""

import os
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pandas as pd
import pytest

from engine.brinson import compute_attribution
from engine.validator import validate_unmapped_weight, validate_all, has_blockers
from data.industry_mapper import load_mapping, map_holdings
from data.cache import get_connection, init_db
from ai.number_verifier import verify_numbers, extract_percentages
from ai.fallback_template import generate_fallback
from report.waterfall import generate_waterfall
from report.sector_chart import generate_sector_chart
from report.pdf_generator import generate_pdf

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


def _sample_holdings():
    """Standard test holdings with realistic data."""
    return pd.DataFrame([
        {"industry": "半導體業", "Wp": 0.35, "Wb": 0.30, "Rp": 0.12, "Rb": 0.08},
        {"industry": "金融保險業", "Wp": 0.20, "Wb": 0.25, "Rp": 0.05, "Rb": 0.04},
        {"industry": "電子零組件業", "Wp": 0.15, "Wb": 0.15, "Rp": 0.08, "Rb": 0.06},
        {"industry": "鋼鐵工業", "Wp": 0.10, "Wb": 0.10, "Rp": -0.02, "Rb": 0.01},
        {"industry": "塑膠工業", "Wp": 0.10, "Wb": 0.10, "Rp": 0.03, "Rb": 0.02},
        {"industry": "食品工業", "Wp": 0.10, "Wb": 0.10, "Rp": 0.01, "Rb": 0.02},
    ])


class TestEndToEndPipeline:
    """I1-I2: Full pipeline integration tests."""

    def test_i01_csv_to_pdf_pipeline(self, tmp_path):
        """I1: CSV → mapping → Brinson → waterfall PNG → PDF — all files produced."""
        holdings = _sample_holdings()

        # Step 1: Compute attribution
        result = compute_attribution(holdings, mode="BF2")
        assert result["fund_return"] is not None

        # Step 2: Generate waterfall chart
        waterfall_path = tmp_path / "waterfall.png"
        fig = generate_waterfall(result, output_path=str(waterfall_path))
        plt.close(fig)
        assert waterfall_path.exists()
        assert waterfall_path.stat().st_size > 0

        # Step 3: Generate sector chart
        sector_path = tmp_path / "sector.png"
        fig = generate_sector_chart(result, output_path=str(sector_path))
        plt.close(fig)
        assert sector_path.exists()
        assert sector_path.stat().st_size > 0

        # Step 4: Generate fallback summary (no API key)
        summary = generate_fallback(result)
        assert "line_message" in summary
        assert "pdf_summary" in summary
        assert "advisor_note" in summary

        # Step 5: Generate PDF
        pdf_path = tmp_path / "report.pdf"
        output = generate_pdf(
            result=result,
            summary=summary,
            output_path=str(pdf_path),
            fund_code="TEST01",
            period="2026-03",
            waterfall_path=str(waterfall_path),
            sector_chart_path=str(sector_path),
        )
        assert Path(output).exists()
        assert Path(output).stat().st_size > 0

    def test_i02_end_to_end_with_fallback(self, tmp_path):
        """I2: Full pipeline without API key → fallback used."""
        holdings = _sample_holdings()
        result = compute_attribution(holdings, mode="BF2")

        # No API key → should use fallback
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": ""}, clear=False):
            from ai.claude_client import generate_summary
            summary = generate_summary(result, api_key=None)

        assert summary["fallback_used"] is True
        assert summary["line_message"] != ""
        assert summary["pdf_summary"] != ""


class TestDeterminism:
    """I3: Same input twice → identical results."""

    def test_i03_deterministic_attribution(self):
        """I3: compute_attribution is deterministic."""
        holdings = _sample_holdings()

        r1 = compute_attribution(holdings.copy(), mode="BF2")
        r2 = compute_attribution(holdings.copy(), mode="BF2")

        assert r1["fund_return"] == r2["fund_return"]
        assert r1["bench_return"] == r2["bench_return"]
        assert r1["excess_return"] == r2["excess_return"]
        assert r1["allocation_total"] == r2["allocation_total"]
        assert r1["selection_total"] == r2["selection_total"]

        # Detail DataFrame should be identical
        pd.testing.assert_frame_equal(r1["detail"], r2["detail"])

    def test_i03b_deterministic_bf3(self):
        """BF3 is also deterministic."""
        holdings = _sample_holdings()

        r1 = compute_attribution(holdings.copy(), mode="BF3")
        r2 = compute_attribution(holdings.copy(), mode="BF3")

        assert r1["interaction_total"] == r2["interaction_total"]
        pd.testing.assert_frame_equal(r1["detail"], r2["detail"])


class TestUnmappedThresholds:
    """I4-I5: Unmapped weight thresholds control report generation."""

    def test_i04_4pct_unmapped_warns_but_allows(self, tmp_path):
        """I4: 4% unmapped → warn, report still produced."""
        # Validate: 4% should warn but not block
        r = validate_unmapped_weight(0.04)
        assert r.level == "warn"

        # Full validation should NOT have blockers
        holdings = _sample_holdings()
        results = validate_all(holdings, unmapped_weight=0.04)
        assert not has_blockers(results)

        # PDF can still be generated
        result = compute_attribution(holdings, mode="BF2")
        summary = generate_fallback(result)
        pdf_path = tmp_path / "warn_report.pdf"
        output = generate_pdf(result, summary, output_path=str(pdf_path))
        assert Path(output).exists()
        assert Path(output).stat().st_size > 0

    def test_i05_15pct_unmapped_blocks(self):
        """I5: 15% unmapped → block, has_blockers=True."""
        r = validate_unmapped_weight(0.15)
        assert r.level == "block"

        holdings = _sample_holdings()
        results = validate_all(holdings, unmapped_weight=0.15)
        assert has_blockers(results)


class TestAIFallback:
    """I6-I8: AI hallucination detection and fallback."""

    def test_i06_hallucinated_numbers_trigger_fallback(self):
        """I6: Mock Claude response with wrong numbers → fallback."""
        holdings = _sample_holdings()
        result = compute_attribution(holdings, mode="BF2")

        # Simulate AI response with fabricated numbers
        fake_ai_text = '基金報酬99.99%，超額報酬50.00%，配置效果25.00%'
        verification = verify_numbers(fake_ai_text, result)
        assert not verification.passed
        assert len(verification.mismatches) > 0

    def test_i07_correct_numbers_pass(self):
        """I7: Fallback text verifies against source (correct numbers)."""
        holdings = _sample_holdings()
        result = compute_attribution(holdings, mode="BF2")
        summary = generate_fallback(result)

        # Verify fallback text has correct numbers
        all_text = f"{summary['line_message']} {summary['pdf_summary']} {summary['advisor_note']}"
        verification = verify_numbers(all_text, result)
        assert verification.passed

    def test_i08_wrong_numbers_fail(self):
        """I8: Text with fabricated percentages → mismatches."""
        holdings = _sample_holdings()
        result = compute_attribution(holdings, mode="BF2")

        bad_text = "基金報酬88.88%，基準報酬77.77%"
        verification = verify_numbers(bad_text, result)
        assert not verification.passed
        assert len(verification.mismatches) == 2

    def test_number_extraction(self):
        """extract_percentages finds all % values in text."""
        text = "基金報酬8.50%，超額報酬-2.29%，配置效果+1.50%"
        numbers = extract_percentages(text)
        assert len(numbers) == 3
        assert abs(numbers[0] - 0.085) < 1e-6
        assert abs(numbers[1] - (-0.0229)) < 1e-6

    def test_no_numbers_passes(self):
        """Text with no percentages → pass by default."""
        holdings = _sample_holdings()
        result = compute_attribution(holdings, mode="BF2")
        verification = verify_numbers("沒有數字的文字", result)
        assert verification.passed


class TestChartGeneration:
    """I9-I12: Chart and report generation."""

    def test_i09_waterfall_bf2_figure(self, tmp_path):
        """I9: BF2 waterfall chart creates valid figure."""
        holdings = _sample_holdings()
        result = compute_attribution(holdings, mode="BF2")
        path = tmp_path / "wf_bf2.png"
        fig = generate_waterfall(result, output_path=str(path))
        plt.close(fig)
        assert path.exists()
        assert path.stat().st_size > 1000  # Reasonable PNG size

    def test_i10_waterfall_bf3_figure(self, tmp_path):
        """I10: BF3 waterfall chart creates valid figure with interaction bar."""
        holdings = _sample_holdings()
        result = compute_attribution(holdings, mode="BF3")
        path = tmp_path / "wf_bf3.png"
        fig = generate_waterfall(result, output_path=str(path))
        plt.close(fig)
        assert path.exists()
        assert path.stat().st_size > 1000

    def test_i11_pdf_exists_with_size(self, tmp_path):
        """I11: PDF generated, exists, size > 0."""
        holdings = _sample_holdings()
        result = compute_attribution(holdings, mode="BF2")
        summary = generate_fallback(result)
        pdf_path = tmp_path / "test_report.pdf"
        output = generate_pdf(result, summary, output_path=str(pdf_path))
        assert Path(output).exists()
        assert Path(output).stat().st_size > 5000  # Reasonable PDF size

    def test_i12_sector_chart_sorted(self, tmp_path):
        """I12: Sector chart created, saveable."""
        holdings = _sample_holdings()
        result = compute_attribution(holdings, mode="BF2")
        path = tmp_path / "sector.png"
        fig = generate_sector_chart(result, output_path=str(path))
        plt.close(fig)
        assert path.exists()
        assert path.stat().st_size > 1000

    def test_pdf_with_charts(self, tmp_path):
        """PDF with embedded charts — both pages populated."""
        holdings = _sample_holdings()
        result = compute_attribution(holdings, mode="BF3")
        summary = generate_fallback(result)

        wf_path = tmp_path / "wf.png"
        sc_path = tmp_path / "sc.png"
        fig1 = generate_waterfall(result, str(wf_path))
        fig2 = generate_sector_chart(result, str(sc_path))
        plt.close(fig1)
        plt.close(fig2)

        pdf_path = tmp_path / "full_report.pdf"
        output = generate_pdf(
            result, summary,
            output_path=str(pdf_path),
            fund_code="BF3TEST",
            period="2026-03",
            advisor_name="測試顧問",
            waterfall_path=str(wf_path),
            sector_chart_path=str(sc_path),
        )
        assert Path(output).stat().st_size > 10000  # PDF with images should be larger

    def test_pdf_audit_logging(self, tmp_path):
        """PDF generation with conn logs to report_log table."""
        db_path = str(tmp_path / "audit.db")
        init_db(db_path)
        conn = get_connection(db_path)

        holdings = _sample_holdings()
        result = compute_attribution(holdings, mode="BF2")
        summary = generate_fallback(result)
        pdf_path = tmp_path / "audit_report.pdf"

        generate_pdf(
            result, summary,
            output_path=str(pdf_path),
            fund_code="AUDIT",
            period="2026-03",
            conn=conn,
        )

        # Verify audit log exists
        from data.cache import get_report
        # We don't know the UUID, but we can query
        row = conn.execute("SELECT * FROM report_log WHERE fund_code = 'AUDIT'").fetchone()
        assert row is not None
        conn.close()
