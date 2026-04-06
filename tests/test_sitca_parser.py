"""Tests for data/sitca_parser.py — SITCA Excel parsing + golden dataset compatibility."""

from pathlib import Path

import pandas as pd
import pytest

from data.sitca_parser import parse_sitca_excel, parse_and_cache

GOLDEN_DIR = Path(__file__).parent / "golden_data"


class TestGoldenDatasetParsing:
    """All 3 golden dataset funds must parse successfully."""

    @pytest.mark.parametrize("filename,expected_rows", [
        ("fund_1.xlsx", 11),
        ("fund_2.xlsx", 11),
        ("fund_3.xlsx", 8),
    ])
    def test_parse_golden_fund(self, filename, expected_rows):
        path = GOLDEN_DIR / filename
        df = parse_sitca_excel(path, sheet_name="holdings")
        assert len(df) == expected_rows
        assert list(df.columns) == ["industry", "weight", "return_rate"]
        assert df["weight"].dtype == float
        assert df["return_rate"].dtype == float

    def test_golden_fund1_weights_reasonable(self):
        df = parse_sitca_excel(GOLDEN_DIR / "fund_1.xlsx", sheet_name="holdings")
        total_weight = df["weight"].sum()
        assert 0.95 <= total_weight <= 1.05, f"Total weight: {total_weight}"

    def test_golden_fund3_has_cash(self):
        df = parse_sitca_excel(GOLDEN_DIR / "fund_3.xlsx", sheet_name="holdings")
        cash = df[df["industry"] == "現金"]
        assert len(cash) == 1
        assert cash.iloc[0]["return_rate"] == 0.0


class TestSITCAFormatParsing:
    """Test parsing of SITCA-style Excel with Chinese headers."""

    @pytest.fixture
    def sitca_file(self, tmp_path):
        """Create a SITCA-style Excel fixture."""
        df = pd.DataFrame({
            "產業類別": ["半導體業", "金融保險業", "電子零組件業", "航運業"],
            "比重": [42.0, 14.0, 10.0, 5.0],  # percentages
            "報酬率": [8.5, 3.0, 5.5, 6.0],    # percentages
        })
        path = tmp_path / "sitca_test.xlsx"
        df.to_excel(path, index=False)
        return path

    def test_parse_sitca_format(self, sitca_file):
        df = parse_sitca_excel(sitca_file)
        assert len(df) == 4
        assert list(df.columns) == ["industry", "weight", "return_rate"]
        # Weights should be converted from percentage to proportion
        assert df.iloc[0]["weight"] == pytest.approx(0.42)
        assert df.iloc[0]["return_rate"] == pytest.approx(0.085)

    @pytest.fixture
    def sitca_market_value_file(self, tmp_path):
        """SITCA file with market values instead of weights."""
        df = pd.DataFrame({
            "產業": ["半導體業", "金融保險業", "其他電子業"],
            "市值": [1000000, 500000, 500000],
        })
        path = tmp_path / "sitca_mv.xlsx"
        df.to_excel(path, index=False)
        return path

    def test_parse_market_value_to_weight(self, sitca_market_value_file):
        df = parse_sitca_excel(sitca_market_value_file)
        assert len(df) == 3
        assert df.iloc[0]["weight"] == pytest.approx(0.5)
        assert df.iloc[1]["weight"] == pytest.approx(0.25)
        assert pd.isna(df.iloc[0]["return_rate"])


class TestEdgeCases:
    def test_file_not_found(self):
        with pytest.raises(FileNotFoundError):
            parse_sitca_excel("/nonexistent/file.xlsx")

    def test_empty_file(self, tmp_path):
        path = tmp_path / "empty.xlsx"
        pd.DataFrame().to_excel(path, index=False)
        with pytest.raises(ValueError, match="Empty"):
            parse_sitca_excel(path)

    def test_missing_columns(self, tmp_path):
        path = tmp_path / "bad_cols.xlsx"
        pd.DataFrame({"foo": [1], "bar": [2]}).to_excel(path, index=False)
        with pytest.raises(ValueError, match="Cannot find industry column"):
            parse_sitca_excel(path)

    def test_zero_weight_rows_filtered(self, tmp_path):
        df = pd.DataFrame({
            "產業": ["半導體業", "金融保險業", "已清算"],
            "比重": [50.0, 50.0, 0.0],
        })
        path = tmp_path / "with_zero.xlsx"
        df.to_excel(path, index=False)
        result = parse_sitca_excel(path)
        assert len(result) == 2


class TestParseAndCache:
    def test_cache_integration(self, tmp_path):
        from data.cache import get_connection, init_db, get_fund_holdings

        db_path = str(tmp_path / "test.db")
        init_db(db_path)
        conn = get_connection(db_path)

        path = GOLDEN_DIR / "fund_1.xlsx"
        df = parse_and_cache(path, "0050", "2026-03", conn=conn, sheet_name="holdings")

        assert len(df) == 11

        # Verify cached
        cached = get_fund_holdings(conn, "0050", "2026-03")
        assert cached is not None
        assert len(cached) == 11
        industries = {r["industry"] for r in cached}
        assert "半導體業" in industries

        conn.close()
