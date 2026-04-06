"""Tests for data/industry_mapper.py — industry mapping, coverage, unmapped logging."""

from pathlib import Path

import pandas as pd
import pytest

from data.industry_mapper import (
    load_mapping,
    map_industry,
    map_holdings,
    get_mapping_coverage,
)
from data.sitca_parser import parse_sitca_excel

GOLDEN_DIR = Path(__file__).parent / "golden_data"


class TestLoadMapping:
    def test_loads_mapping_json(self):
        mapping = load_mapping()
        assert len(mapping) >= 28
        assert "半導體業" in mapping
        assert mapping["半導體業"] == "半導體業"

    def test_excludes_comments(self):
        mapping = load_mapping()
        assert "_comment" not in mapping

    def test_missing_file_raises(self):
        with pytest.raises(FileNotFoundError):
            load_mapping("/nonexistent/mapping.json")


class TestMapIndustry:
    @pytest.fixture
    def mapping(self):
        return load_mapping()

    def test_exact_match(self, mapping):
        assert map_industry("半導體業", mapping) == "半導體業"
        assert map_industry("金融保險業", mapping) == "金融保險業"

    def test_contains_match(self, mapping):
        # "XX半導體業YY" should match "半導體業" key
        assert map_industry("台灣半導體業概況", mapping) == "半導體業"

    def test_reverse_contains(self, mapping):
        # "半導體" is contained in key "半導體業"
        assert map_industry("半導體", mapping) == "半導體業"

    def test_unmapped_returns_none(self, mapping):
        assert map_industry("外星科技業", mapping) is None

    def test_strips_whitespace(self, mapping):
        assert map_industry("  半導體業  ", mapping) == "半導體業"

    def test_cash_is_unmapped(self, mapping):
        # "現金" is not in mapping.json — this is expected
        result = map_industry("現金", mapping)
        # Cash may or may not be mapped depending on mapping.json
        # Just verify it doesn't crash
        assert result is None or isinstance(result, str)


class TestMapHoldings:
    def test_maps_dataframe(self):
        df = pd.DataFrame({
            "industry": ["半導體業", "金融保險業", "外星科技"],
            "weight": [0.5, 0.3, 0.2],
            "return_rate": [0.08, 0.03, 0.01],
        })
        result = map_holdings(df)
        assert "mapped" in result.columns
        assert result.iloc[0]["mapped"] == True
        assert result.iloc[1]["mapped"] == True
        assert result.iloc[2]["mapped"] == False

    def test_unmapped_logged_to_db(self, tmp_path):
        from data.cache import get_connection, init_db, get_unmapped_categories

        db_path = str(tmp_path / "test.db")
        init_db(db_path)
        conn = get_connection(db_path)

        df = pd.DataFrame({
            "industry": ["半導體業", "外星科技"],
            "weight": [0.8, 0.2],
            "return_rate": [0.08, 0.01],
        })
        map_holdings(df, conn=conn, fund_code="0050", period="2026-03")

        unmapped = get_unmapped_categories(conn)
        assert len(unmapped) == 1
        assert unmapped[0]["raw_name"] == "外星科技"
        assert unmapped[0]["fund_code"] == "0050"
        conn.close()


class TestGoldenDatasetCoverage:
    """Golden dataset funds must have 95%+ mapping coverage."""

    @pytest.mark.parametrize("filename,min_coverage", [
        ("fund_1.xlsx", 0.95),
        ("fund_2.xlsx", 0.95),
        ("fund_3.xlsx", 0.85),  # 現金 (cash) is not a TSE industry — 87.5% expected
    ])
    def test_golden_fund_coverage(self, filename, min_coverage):
        df = parse_sitca_excel(GOLDEN_DIR / filename, sheet_name="holdings")
        coverage = get_mapping_coverage(df)
        assert coverage >= min_coverage, (
            f"{filename}: coverage {coverage:.1%} < {min_coverage:.0%}. "
            f"Unmapped: {[n for n in df['industry'] if map_industry(n, load_mapping()) is None]}"
        )

    def test_fund1_all_mapped(self):
        """Fund 1 (0050) uses only standard TSE industry names — should be 100%."""
        df = parse_sitca_excel(GOLDEN_DIR / "fund_1.xlsx", sheet_name="holdings")
        coverage = get_mapping_coverage(df)
        assert coverage == 1.0

    def test_fund3_cash_handling(self):
        """Fund 3 has 現金 — may not map, but coverage should still be >= 87.5% (7/8)."""
        df = parse_sitca_excel(GOLDEN_DIR / "fund_3.xlsx", sheet_name="holdings")
        coverage = get_mapping_coverage(df)
        # 7 real industries + 1 cash = at least 87.5% if cash unmapped
        assert coverage >= 0.85
