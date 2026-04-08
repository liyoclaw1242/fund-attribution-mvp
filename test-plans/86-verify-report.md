# Verify Report: BE: International fetchers — Finnhub, yfinance, FX + currency/weight transformers

- **Issue**: liyoclaw1242/fund-attribution-mvp#86
- **PR**: #92
- **Verifier**: qa-20260408-0847587
- **Date**: 2026-04-08
- **Verdict**: PASS

## Results

| Step | Description | Result | Notes |
|------|-------------|--------|-------|
| A1 | FinnhubFetcher writes to fund_holding | PASS | API key validation, rate limiting (1s/call), per-fund error isolation |
| A2 | YfinanceFetcher writes to stock_price | PASS | Batch download, 36 default tickers, GICS→unified sector mapping |
| A3 | YfinanceInfoFetcher writes to stock_info | PASS | Weekly sector/market cap info |
| A4 | FxRateFetcher writes to fx_rate | PASS | 6 default pairs, API + fallback rates |
| A5 | Currency convert() works | PASS | TWD passthrough, date-based lookup with fallback to most recent, ValueError on missing |
| A6 | WeightCalculator produces industry_weight | PASS | SQL aggregation, weights sum to 1.0, pool injection via params |
| A7 | All fetchers log to pipeline_run | PASS | Via BaseFetcher._log_run inheritance |
| A8 | API key warn without crash | PASS | Finnhub logs warning, returns empty list |
| A9 | Error isolation | PASS | Per-ticker/fund try/except, FX fallback rates |
| A10 | No out-of-scope changes | PASS | 8 files, all in spec |
| A11 | 30/30 tests pass | PASS | All green |

## Summary

Clean, well-structured implementation. All 5 deliverables present with proper error handling, fallback strategies, and test coverage. No scope creep.
