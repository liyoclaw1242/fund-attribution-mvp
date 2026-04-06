# Test Plan: Sprint 4: QA 全面測試（Smoke + UAT + Edge Cases）

- **Issue**: liyoclaw1242/fund-attribution-mvp#15
- **Author**: qa-20260406-0956311
- **Date**: 2026-04-06
- **Dimensions**: API / DB / Unit / Integration

## Prerequisites

- [ ] Python 3.10+ with dependencies installed (`pip install -r requirements.txt`)
- [ ] SQLite3 available
- [ ] No ANTHROPIC_API_KEY needed (fallback tests only)

## Unit Tests — Brinson Edge Cases (`tests/test_brinson_edge.py`)

### U1: 100% cash fund (BF2)
- **Action**: Wp=1.0 cash, Wb=0 cash / Wb=1.0 benchmark industry
- **Expected**: fund_return=0, excess negative, allocation captures all drag

### U2: 100% cash fund (BF3)
- **Action**: Same as U1 but BF3
- **Expected**: Allocation + Selection + Interaction = excess_return

### U3: Single industry — same weight
- **Action**: One industry, Wp=Wb=1.0, Rp > Rb
- **Expected**: allocation=0, selection=excess

### U4: All negative returns
- **Action**: All Rp and Rb negative
- **Expected**: No crash, invariant holds

### U5: All zero returns
- **Action**: Rp=Rb=0 for all industries
- **Expected**: All effects = 0

### U6: Identical fund and benchmark
- **Action**: Wp=Wb, Rp=Rb for all industries
- **Expected**: excess=0, all effects ≈ 0

### U7: Extreme overweight single industry
- **Action**: Wp=0.95 one industry, Wp=0.05 other
- **Expected**: Runs, invariant holds

### U8: Many industries (20+)
- **Action**: 20 industries with varied weights/returns
- **Expected**: Top/bottom 3 correct, invariant holds

### U9: Near-zero excess (floating point precision)
- **Action**: Construct data where excess ≈ 1e-15
- **Expected**: No assertion error, excess ≈ 0

### U10: Large positive returns
- **Action**: Rp=0.45 (45%), Rb=0.40
- **Expected**: Runs correctly

### U11: Large negative returns
- **Action**: Rp=-0.40 (-40%), Rb=-0.30
- **Expected**: Runs correctly

### U12: Cash + benchmark (cash return = 0)
- **Action**: Cash industry with Rp=0, Rb=0, plus normal industry
- **Expected**: Cash allocation effect negative in up market

### U13: BF2 vs BF3 — same data, different decomposition
- **Action**: Same holdings, run BF2 and BF3
- **Expected**: Both have same excess_return; BF2 interaction=None, BF3 interaction≠None

### U14: Reversed top/bottom contributors
- **Action**: Holdings where top contributor is clearly identifiable
- **Expected**: top_contributors[0] has highest total_contrib

### U15: Single row — minimum valid input
- **Action**: One industry row with valid columns
- **Expected**: Runs without error

### U16: Two industries equal contribution
- **Action**: Two industries with identical total_contrib
- **Expected**: Both appear in results, no crash

### U17: Zero fund weight, positive benchmark weight
- **Action**: Wp=0 for one industry, Wb>0
- **Expected**: Selection=0 for that industry (BF2), correct allocation

### U18: Zero benchmark weight, positive fund weight
- **Action**: Wb=0 for one industry, Wp>0
- **Expected**: Allocation effect captures overweight vs 0 benchmark

### U19: Mixed sign returns across industries
- **Action**: Some Rp positive, some negative
- **Expected**: Effects calculated correctly, invariant holds

### U20: Very small weights (1e-6)
- **Action**: Very small weights for some industries
- **Expected**: No division errors, contributions near zero

## Unit Tests — Data Pipeline (`tests/test_data_pipeline.py`)

### D1: Fund weight sum = 1.0
- **Action**: validate_fund_weights with exact sum=1.0
- **Expected**: level="pass"

### D2: Fund weight sum out of tolerance
- **Action**: validate_fund_weights with sum=0.85
- **Expected**: level="block"

### D3: Unmapped weight at warn threshold (4%)
- **Action**: validate_unmapped_weight(0.04)
- **Expected**: level="warn"

### D4: Unmapped weight at block threshold (15%)
- **Action**: validate_unmapped_weight(0.15)
- **Expected**: level="block"

### D5: Cache hit — data within TTL
- **Action**: upsert then get immediately
- **Expected**: Returns cached data

### D6: Cache miss — data expired
- **Action**: upsert with ttl=0, wait, then get
- **Expected**: Returns None

### D7: Cache miss — key not found
- **Action**: get non-existent fund code
- **Expected**: Returns None

### D8: Industry mapping — exact match
- **Action**: map_industry("半導體業", mapping)
- **Expected**: Returns standard name

### D9: Industry mapping — contains match
- **Action**: map_industry with raw name containing key
- **Expected**: Returns standard name

### D10: Industry mapping — unmapped
- **Action**: map_industry with unknown name
- **Expected**: Returns None

### D11: map_holdings — coverage ratio
- **Action**: get_mapping_coverage with mix of mapped/unmapped
- **Expected**: Returns correct ratio (0.0-1.0)

### D12: Purge expired removes stale entries
- **Action**: Insert expired, call purge_expired
- **Expected**: Returns count > 0

## Integration Tests (`tests/test_integration.py`)

### I1: CSV upload → mapping → Brinson → waterfall PNG → PDF
- **Action**: Parse CSV, map industries, compute attribution, generate charts, generate PDF
- **Expected**: All files produced, size > 0

### I2: Fund code → SITCA → mapping → Brinson → AI (fallback)
- **Action**: End-to-end with mock SITCA data, no API key
- **Expected**: Fallback used, all outputs generated

### I3: Determinism — same input twice → byte-identical results
- **Action**: Run compute_attribution twice with same input
- **Expected**: AttributionResult values identical

### I4: 4% unmapped → warning displayed, report produced with disclaimer
- **Action**: Holdings with 4% unmapped weight
- **Expected**: validate_unmapped_weight returns "warn", PDF still generated

### I5: 15% unmapped → report blocked, error message, no PDF
- **Action**: Holdings with 15% unmapped weight
- **Expected**: validate_unmapped_weight returns "block", has_blockers=True

### I6: AI hallucination → fallback activated
- **Action**: Mock Claude response with wrong numbers
- **Expected**: verify_numbers fails, fallback_used=True

### I7: Number verifier — correct numbers pass
- **Action**: Generate fallback text, verify against source
- **Expected**: verification passed=True

### I8: Number verifier — wrong numbers fail
- **Action**: Text with fabricated percentages
- **Expected**: verification passed=False, mismatches non-empty

### I9: Waterfall chart — BF2 has 4 bars
- **Action**: generate_waterfall with BF2 result
- **Expected**: Figure created, saveable as PNG

### I10: Waterfall chart — BF3 has 5 bars
- **Action**: generate_waterfall with BF3 result
- **Expected**: Figure created with interaction bar

### I11: PDF — contains disclaimer text
- **Action**: Generate PDF, read file
- **Expected**: File exists, size > 0

### I12: Sector chart — sorted by contribution
- **Action**: generate_sector_chart
- **Expected**: Figure created, saveable as PNG

## Smoke Test (`tests/test_smoke.py`)

### S1: 10 synthetic funds — all produce valid reports within 60s
- **Action**: Generate 10 synthetic holdings, run full pipeline
- **Expected**: All 10 complete, each producing AttributionResult + waterfall + PDF, total < 60s

## Edge Cases

### E1: Empty DataFrame — should raise ValueError
- **Action**: compute_attribution(pd.DataFrame())
- **Expected**: ValueError raised

### E2: Missing column — should raise ValueError
- **Action**: DataFrame without 'Rb' column
- **Expected**: ValueError with "Missing required columns"

### E3: NaN in weights — should not crash silently
- **Action**: DataFrame with NaN in Wp
- **Expected**: Result still computes (NaN propagation) or error

### E4: Negative weights — unusual but should compute
- **Action**: Wp=-0.1 (short position)
- **Expected**: Runs, invariant holds

## Coverage Check

- [x] Every acceptance criterion has at least one test step
- [x] Happy path covered for each dimension
- [x] Error/edge cases covered
- [x] Prerequisites specified
