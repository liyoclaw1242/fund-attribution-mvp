"""Tests for `pipeline._dates.coerce_date` — the shared helper used by
every fetcher that hands a date value to asyncpg."""

from datetime import date, datetime

import pytest

from pipeline._dates import coerce_date
from pipeline.transformers.weight_calculator import _coerce_date as legacy_alias


class TestCoerceDate:
    def test_none_returns_today(self):
        assert coerce_date(None) == date.today()

    def test_date_passthrough(self):
        d = date(2026, 4, 11)
        assert coerce_date(d) is d

    def test_datetime_narrowed_to_date(self):
        result = coerce_date(datetime(2026, 4, 11, 13, 45))
        assert result == date(2026, 4, 11)
        assert type(result) is date  # not datetime

    def test_iso_string_parsed(self):
        assert coerce_date("2026-04-11") == date(2026, 4, 11)

    def test_bad_type_raises(self):
        with pytest.raises(TypeError, match="unsupported date value"):
            coerce_date(12345)

    def test_empty_string_raises_via_fromisoformat(self):
        with pytest.raises(ValueError):
            coerce_date("")


class TestWeightCalculatorAlias:
    def test_alias_points_to_shared_helper(self):
        """weight_calculator still re-exports _coerce_date for tests that
        imported it before the shared helper moved to pipeline._dates."""
        assert legacy_alias is coerce_date
