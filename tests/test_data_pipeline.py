"""Data pipeline tests — weight validation, unmapped alerts, cache hit/miss, mapping.

Covers: fund weight sums, unmapped thresholds, cache TTL, industry mapping coverage.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pandas as pd
import pytest

from data.cache import (
    get_connection,
    init_db,
    get_fund_holdings,
    upsert_fund_holdings,
    purge_expired,
)
from data.industry_mapper import (
    load_mapping,
    map_industry,
    map_holdings,
    get_mapping_coverage,
)
from engine.validator import (
    validate_fund_weights,
    validate_unmapped_weight,
    validate_benchmark_weights,
    validate_all,
    has_blockers,
)


@pytest.fixture
def db(tmp_path):
    db_path = str(tmp_path / "test_pipeline.db")
    init_db(db_path)
    conn = get_connection(db_path)
    yield conn
    conn.close()


@pytest.fixture
def mapping():
    return load_mapping()


# ── Weight Sum Validation ──────────────────────────────────────────

class TestWeightSums:
    def test_d01_fund_weight_sum_exact(self):
        """D1: Fund weights sum to exactly 1.0 → pass."""
        df = pd.DataFrame({"Wp": [0.3, 0.3, 0.4]})
        assert validate_fund_weights(df).level == "pass"

    def test_d01b_fund_weight_within_tolerance(self):
        """Fund weights sum to 0.99 (within ±2%) → pass."""
        df = pd.DataFrame({"Wp": [0.3, 0.3, 0.39]})
        assert validate_fund_weights(df).level == "pass"

    def test_d02_fund_weight_out_of_tolerance(self):
        """D2: Fund weights sum to 0.85 → block."""
        df = pd.DataFrame({"Wp": [0.5, 0.35]})
        assert validate_fund_weights(df).level == "block"

    def test_fund_weight_above_tolerance(self):
        """Fund weights sum to 1.05 → block."""
        df = pd.DataFrame({"Wp": [0.6, 0.45]})
        assert validate_fund_weights(df).level == "block"

    def test_benchmark_weight_exact(self):
        """Benchmark weights sum to exactly 1.0 → pass."""
        df = pd.DataFrame({"Wb": [0.6, 0.4]})
        assert validate_benchmark_weights(df).level == "pass"

    def test_benchmark_weight_inexact(self):
        """Benchmark weights sum ≠ 1.0 → block."""
        df = pd.DataFrame({"Wb": [0.6, 0.39]})
        assert validate_benchmark_weights(df).level == "block"


# ── Unmapped Weight Alerts ─────────────────────────────────────────

class TestUnmappedAlerts:
    def test_d03_unmapped_4pct_warns(self):
        """D3: 4% unmapped weight → warn (above 3% threshold)."""
        r = validate_unmapped_weight(0.04)
        assert r.level == "warn"

    def test_d04_unmapped_15pct_blocks(self):
        """D4: 15% unmapped weight → block (above 10% threshold)."""
        r = validate_unmapped_weight(0.15)
        assert r.level == "block"

    def test_unmapped_2pct_passes(self):
        """2% unmapped → pass (below 3% threshold)."""
        r = validate_unmapped_weight(0.02)
        assert r.level == "pass"

    def test_unmapped_exactly_3pct_warns(self):
        """Exactly 3% unmapped → warn."""
        r = validate_unmapped_weight(0.03)
        assert r.level == "warn"

    def test_unmapped_exactly_10pct_blocks(self):
        """Exactly 10% unmapped → block."""
        r = validate_unmapped_weight(0.10)
        assert r.level == "block"

    def test_unmapped_zero_passes(self):
        """Zero unmapped → pass."""
        r = validate_unmapped_weight(0.0)
        assert r.level == "pass"

    def test_validate_all_with_high_unmapped_blocks(self):
        """Full pipeline validation with 15% unmapped → has_blockers=True."""
        df = pd.DataFrame({
            "industry": ["A", "B"],
            "Wp": [0.5, 0.5],
            "Wb": [0.5, 0.5],
            "Rp": [0.05, 0.03],
            "Rb": [0.04, 0.02],
        })
        results = validate_all(df, unmapped_weight=0.15, data_timestamp=datetime.now())
        assert has_blockers(results)


# ── Cache Hit/Miss ─────────────────────────────────────────────────

SAMPLE_HOLDINGS = [
    {"industry": "半導體", "weight": 0.35, "return_rate": 0.12},
    {"industry": "金融保險", "weight": 0.15, "return_rate": 0.05},
]


class TestCacheHitMiss:
    def test_d05_cache_hit_within_ttl(self, db):
        """D5: Data within TTL → returns cached data."""
        upsert_fund_holdings(db, "0050", "2026-03", SAMPLE_HOLDINGS, ttl_hours=24)
        result = get_fund_holdings(db, "0050", "2026-03")
        assert result is not None
        assert len(result) == 2
        assert result[0]["industry"] == "半導體"

    def test_d06_cache_miss_expired(self, db):
        """D6: Data expired → returns None."""
        upsert_fund_holdings(db, "0050", "2026-03", SAMPLE_HOLDINGS, ttl_hours=0)
        future = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(seconds=1)
        with patch("data.cache._utcnow", return_value=future):
            result = get_fund_holdings(db, "0050", "2026-03")
        assert result is None

    def test_d07_cache_miss_not_found(self, db):
        """D7: Non-existent key → returns None."""
        result = get_fund_holdings(db, "XXXX", "2099-01")
        assert result is None

    def test_d12_purge_expired(self, db):
        """D12: Purge removes expired entries."""
        upsert_fund_holdings(db, "0050", "2026-03", SAMPLE_HOLDINGS, ttl_hours=0)
        future = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(seconds=1)
        with patch("data.cache._utcnow", return_value=future):
            deleted = purge_expired(db)
        assert deleted >= 1

    def test_cache_overwrite_adds_rows(self, db):
        """Upserting same fund/period adds new industry rows."""
        upsert_fund_holdings(db, "0050", "2026-03", SAMPLE_HOLDINGS)
        new_holdings = [{"industry": "電子", "weight": 0.50, "return_rate": 0.08}]
        upsert_fund_holdings(db, "0050", "2026-03", new_holdings)
        result = get_fund_holdings(db, "0050", "2026-03")
        assert result is not None
        industries = [r["industry"] for r in result]
        assert "電子" in industries


# ── Industry Mapping ───────────────────────────────────────────────

class TestIndustryMapping:
    def test_d08_exact_match(self, mapping):
        """D8: Exact match in mapping.json."""
        result = map_industry("半導體業", mapping)
        assert result is not None

    def test_d09_contains_match(self, mapping):
        """D9: Contains match — raw name contains mapping key."""
        # If there's a key like "半導體" it should match "XX半導體業XX"
        found = False
        for key in mapping:
            result = map_industry(f"XX{key}YY", mapping)
            if result is not None:
                found = True
                break
        assert found, "No contains match found in mapping"

    def test_d10_unmapped(self, mapping):
        """D10: Completely unknown name → None."""
        result = map_industry("完全不存在的產業XYZ", mapping)
        assert result is None

    def test_d11_mapping_coverage(self, mapping):
        """D11: Coverage ratio with mix of mapped and unmapped."""
        df = pd.DataFrame({"industry": ["半導體業", "金融保險業", "火星產業"]})
        coverage = get_mapping_coverage(df, mapping)
        assert 0.0 < coverage < 1.0  # At least some mapped, some not

    def test_map_holdings_adds_mapped_column(self, mapping):
        """map_holdings adds 'mapped' boolean column."""
        df = pd.DataFrame({
            "industry": ["半導體業", "不存在業"],
            "weight": [0.7, 0.3],
        })
        result = map_holdings(df, mapping)
        assert "mapped" in result.columns
        assert result["mapped"].sum() >= 1  # At least semiconductor mapped

    def test_map_holdings_unmapped_logs(self, db, mapping):
        """map_holdings logs unmapped categories to SQLite when conn provided."""
        df = pd.DataFrame({
            "industry": ["半導體業", "火星產業"],
            "weight": [0.9, 0.1],
        })
        result = map_holdings(df, mapping, conn=db, fund_code="TEST", period="2026-03")
        unmapped_rows = result[~result["mapped"]]
        assert len(unmapped_rows) >= 1
