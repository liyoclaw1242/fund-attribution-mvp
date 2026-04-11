"""Tests for pipeline transformers — currency converter and weight calculator."""

from datetime import date, datetime
from unittest.mock import AsyncMock, MagicMock

import pandas as pd
import pytest

from pipeline.transformers.currency import convert, get_rate
from pipeline.transformers.weight_calculator import WeightCalculator, _coerce_date


def _make_pool_with_conn(mock_conn):
    mock_pool = MagicMock()
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=mock_conn)
    cm.__aexit__ = AsyncMock(return_value=False)
    mock_pool.acquire.return_value = cm
    return mock_pool


# --- Currency converter ---

class TestCurrencyConvert:
    @pytest.mark.asyncio
    async def test_twd_passthrough(self):
        """TWD to TWD returns the same amount, no DB call."""
        mock_pool = MagicMock()
        result = await convert(1000.0, "TWD", "2026-04-08", mock_pool)
        assert result == 1000.0

    @pytest.mark.asyncio
    async def test_usd_to_twd(self):
        mock_conn = AsyncMock()
        mock_conn.fetchrow = AsyncMock(return_value={"rate": 32.15})
        mock_pool = _make_pool_with_conn(mock_conn)

        result = await convert(100.0, "USD", "2026-04-08", mock_pool)
        assert result == 3215.0

    @pytest.mark.asyncio
    async def test_no_rate_raises(self):
        mock_conn = AsyncMock()
        mock_conn.fetchrow = AsyncMock(return_value=None)
        mock_pool = _make_pool_with_conn(mock_conn)

        with pytest.raises(ValueError, match="No FX rate found"):
            await convert(100.0, "GBP", "2026-04-08", mock_pool)


class TestGetRate:
    @pytest.mark.asyncio
    async def test_twd_returns_one(self):
        mock_pool = MagicMock()
        result = await get_rate("TWD", "2026-04-08", mock_pool)
        assert result == 1.0

    @pytest.mark.asyncio
    async def test_fetches_rate(self):
        mock_conn = AsyncMock()
        mock_conn.fetchrow = AsyncMock(return_value={"rate": 4.1})
        mock_pool = _make_pool_with_conn(mock_conn)

        result = await get_rate("HKD", "2026-04-08", mock_pool)
        assert result == 4.1


# --- Weight calculator ---

class TestWeightCalculator:
    def test_source_name(self):
        wc = WeightCalculator()
        assert wc.source_name == "weight_calculator"
        assert wc.target_table == "industry_weight"

    def test_transform_empty(self):
        wc = WeightCalculator()
        df = wc.transform([])
        assert df.empty

    def test_transform_normalizes(self):
        wc = WeightCalculator()
        raw = [{
            "industry": "半導體",
            "date": "2026-04-08",
            "market": "twse",
            "weight": 0.35,
            "market_cap": 15000000000000,
        }]
        df = wc.transform(raw)
        assert list(df.columns) == ["industry", "date", "market", "weight", "market_cap"]
        assert len(df) == 1

    @pytest.mark.asyncio
    async def test_fetch_requires_pool_in_params(self):
        wc = WeightCalculator()
        with pytest.raises(ValueError, match="requires '_pool'"):
            await wc.fetch({})

    @pytest.mark.asyncio
    async def test_compute_weights(self):
        """Weights should sum to 1.0 for a market."""
        wc = WeightCalculator()

        mock_conn = AsyncMock()
        mock_conn.fetch = AsyncMock(return_value=[
            {"industry": "半導體", "total_cap": 7000},
            {"industry": "金融", "total_cap": 3000},
        ])
        mock_pool = _make_pool_with_conn(mock_conn)

        rows = await wc._compute_weights(mock_pool, "twse", "2026-04-08")

        assert len(rows) == 2
        total_weight = sum(r["weight"] for r in rows)
        assert abs(total_weight - 1.0) < 1e-9

        semi = next(r for r in rows if r["industry"] == "半導體")
        assert abs(semi["weight"] - 0.7) < 1e-9

    @pytest.mark.asyncio
    async def test_compute_weights_empty(self):
        wc = WeightCalculator()

        mock_conn = AsyncMock()
        mock_conn.fetch = AsyncMock(return_value=[])
        mock_pool = _make_pool_with_conn(mock_conn)

        rows = await wc._compute_weights(mock_pool, "twse", date(2026, 4, 8))
        assert rows == []


class TestCoerceDate:
    def test_none_returns_today(self):
        assert _coerce_date(None) == date.today()

    def test_date_passthrough(self):
        d = date(2026, 4, 8)
        assert _coerce_date(d) is d

    def test_datetime_narrowed_to_date(self):
        assert _coerce_date(datetime(2026, 4, 8, 13, 45)) == date(2026, 4, 8)

    def test_iso_string_parsed(self):
        assert _coerce_date("2026-04-08") == date(2026, 4, 8)

    def test_bad_type_raises(self):
        with pytest.raises(TypeError, match="unsupported date value"):
            _coerce_date(12345)


class TestWeightCalculatorFetchDateBinding:
    @pytest.mark.asyncio
    async def test_fetch_default_date_is_date_object(self):
        """Regression: default date must be a date, never a str — asyncpg
        binds DATE columns from datetime.date and rejects iso strings."""
        wc = WeightCalculator()

        mock_conn = AsyncMock()
        mock_conn.fetch = AsyncMock(return_value=[
            {"industry": "Semiconductor", "total_cap": 1000},
        ])
        mock_pool = _make_pool_with_conn(mock_conn)

        rows = await wc.fetch({"_pool": mock_pool, "markets": ["twse"]})

        # Each emitted row's `date` must be a datetime.date instance so
        # BaseFetcher._load() can hand it to copy_records_to_table.
        for row in rows:
            assert isinstance(row["date"], date), (
                f"weight_calculator emitted {row['date']!r} (type={type(row['date']).__name__}), "
                f"asyncpg will reject this on the DATE column binding"
            )

        # Confirm that what the SQL call receives is also a date object.
        call_args = mock_conn.fetch.await_args
        assert isinstance(call_args.args[2], date), (
            f"weight_calculator passed {call_args.args[2]!r} as $2 — asyncpg needs datetime.date"
        )

    @pytest.mark.asyncio
    async def test_fetch_accepts_iso_string_date(self):
        wc = WeightCalculator()

        mock_conn = AsyncMock()
        mock_conn.fetch = AsyncMock(return_value=[])
        mock_pool = _make_pool_with_conn(mock_conn)

        await wc.fetch({"_pool": mock_pool, "markets": ["twse"], "date": "2026-03-15"})

        call_args = mock_conn.fetch.await_args
        assert call_args.args[2] == date(2026, 3, 15)
        assert isinstance(call_args.args[2], date)

    @pytest.mark.asyncio
    async def test_fetch_accepts_date_object(self):
        wc = WeightCalculator()

        mock_conn = AsyncMock()
        mock_conn.fetch = AsyncMock(return_value=[])
        mock_pool = _make_pool_with_conn(mock_conn)

        target = date(2026, 3, 15)
        await wc.fetch({"_pool": mock_pool, "markets": ["twse"], "date": target})

        call_args = mock_conn.fetch.await_args
        assert call_args.args[2] is target
