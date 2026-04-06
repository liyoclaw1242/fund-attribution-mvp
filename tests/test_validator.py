"""Tests for engine/validator.py — all 7 validation rules + edge cases."""

from datetime import datetime, timedelta

import pandas as pd
import pytest

from engine.validator import (
    ValidationResult,
    validate_brinson_assertion,
    validate_fund_weights,
    validate_benchmark_weights,
    validate_single_industry_weight,
    validate_monthly_returns,
    validate_data_staleness,
    validate_unmapped_weight,
    validate_all,
    has_blockers,
)


class TestBrinsonAssertion:
    def test_pass_bf2(self):
        r = validate_brinson_assertion(0.003, 0.007, 0.01)
        assert r.level == "pass"

    def test_pass_bf3(self):
        r = validate_brinson_assertion(0.003, 0.004, 0.01, interaction_total=0.003)
        assert r.level == "pass"

    def test_block_on_violation(self):
        r = validate_brinson_assertion(0.003, 0.007, 0.05)
        assert r.level == "block"


class TestFundWeights:
    def test_pass_exact(self):
        df = pd.DataFrame({"Wp": [0.6, 0.4]})
        assert validate_fund_weights(df).level == "pass"

    def test_pass_within_tolerance(self):
        df = pd.DataFrame({"Wp": [0.6, 0.39]})  # sum = 0.99
        assert validate_fund_weights(df).level == "pass"

    def test_block_outside_tolerance(self):
        df = pd.DataFrame({"Wp": [0.6, 0.3]})  # sum = 0.90
        assert validate_fund_weights(df).level == "block"

    def test_uses_weight_column_fallback(self):
        df = pd.DataFrame({"weight": [0.5, 0.5]})
        assert validate_fund_weights(df).level == "pass"


class TestBenchmarkWeights:
    def test_pass_exact(self):
        df = pd.DataFrame({"Wb": [0.6, 0.4]})
        assert validate_benchmark_weights(df).level == "pass"

    def test_block_inexact(self):
        df = pd.DataFrame({"Wb": [0.6, 0.39]})
        assert validate_benchmark_weights(df).level == "block"

    def test_skip_no_column(self):
        df = pd.DataFrame({"Wp": [0.5, 0.5]})
        assert validate_benchmark_weights(df).level == "pass"


class TestSingleIndustryWeight:
    def test_pass_normal(self):
        df = pd.DataFrame({"industry": ["A", "B"], "Wp": [0.5, 0.5]})
        assert validate_single_industry_weight(df).level == "pass"

    def test_warn_overweight(self):
        df = pd.DataFrame({"industry": ["半導體業", "其他"], "Wp": [0.65, 0.35]})
        r = validate_single_industry_weight(df)
        assert r.level == "warn"
        assert "半導體業" in r.message

    def test_exactly_at_threshold(self):
        df = pd.DataFrame({"industry": ["A", "B"], "Wp": [0.60, 0.40]})
        assert validate_single_industry_weight(df).level == "pass"


class TestMonthlyReturns:
    def test_pass_normal(self):
        df = pd.DataFrame({"Rp": [0.05, -0.03, 0.10]})
        assert validate_monthly_returns(df).level == "pass"

    def test_warn_extreme_positive(self):
        df = pd.DataFrame({"industry": ["A", "B"], "Rp": [0.60, 0.05]})
        r = validate_monthly_returns(df)
        assert r.level == "warn"

    def test_warn_extreme_negative(self):
        df = pd.DataFrame({"industry": ["A"], "Rp": [-0.55]})
        assert validate_monthly_returns(df).level == "warn"

    def test_uses_return_rate_fallback(self):
        df = pd.DataFrame({"return_rate": [0.05, 0.03]})
        assert validate_monthly_returns(df).level == "pass"


class TestDataStaleness:
    def test_pass_fresh(self):
        ts = datetime.now() - timedelta(days=10)
        assert validate_data_staleness(ts).level == "pass"

    def test_block_stale(self):
        ts = datetime.now() - timedelta(days=60)
        assert validate_data_staleness(ts).level == "block"

    def test_warn_no_timestamp(self):
        assert validate_data_staleness(None).level == "warn"

    def test_accepts_iso_string(self):
        ts = (datetime.now() - timedelta(days=5)).isoformat()
        assert validate_data_staleness(ts).level == "pass"

    def test_exactly_at_limit(self):
        ts = datetime.now() - timedelta(days=45)
        assert validate_data_staleness(ts).level == "pass"


class TestUnmappedWeight:
    def test_pass_zero(self):
        assert validate_unmapped_weight(0.0).level == "pass"

    def test_pass_below_threshold(self):
        assert validate_unmapped_weight(0.02).level == "pass"

    def test_warn_at_3_percent(self):
        assert validate_unmapped_weight(0.03).level == "warn"

    def test_warn_between_thresholds(self):
        assert validate_unmapped_weight(0.05).level == "warn"

    def test_block_at_10_percent(self):
        assert validate_unmapped_weight(0.10).level == "block"

    def test_block_above_10_percent(self):
        assert validate_unmapped_weight(0.15).level == "block"


class TestValidateAll:
    def test_all_pass(self):
        df = pd.DataFrame({
            "industry": ["A", "B"],
            "Wp": [0.6, 0.4],
            "Wb": [0.5, 0.5],
            "Rp": [0.05, 0.03],
            "Rb": [0.04, 0.02],
        })
        attr = {
            "allocation_total": 0.003,
            "selection_total": 0.007,
            "excess_return": 0.01,
        }
        results = validate_all(df, attribution_result=attr, data_timestamp=datetime.now())
        assert not has_blockers(results)

    def test_has_blockers_detects_block(self):
        results = [
            ValidationResult("test", "pass", "ok"),
            ValidationResult("test2", "block", "bad"),
        ]
        assert has_blockers(results)

    def test_has_blockers_false_when_clean(self):
        results = [
            ValidationResult("test", "pass", "ok"),
            ValidationResult("test2", "warn", "meh"),
        ]
        assert not has_blockers(results)
