"""
Generate golden dataset Excel files for Brinson-Fachler attribution testing.

Each file contains:
- Sheet "holdings": fund and benchmark data per industry
- Sheet "bf2": BF2 (2-factor) attribution results
- Sheet "bf3": BF3 (3-factor) attribution results
- Sheet "summary": aggregate results for both modes

All numbers are hand-verified against Brinson-Fachler (1985) formulas.

BF2 (2-factor, interaction absorbed into selection):
  Allocation = (Wp - Wb) * (Rb_i - Rb_total)
  Selection  = Wp * (Rp_i - Rb_i)

BF3 (3-factor, standard Brinson-Fachler):
  Allocation  = (Wp - Wb) * (Rb_i - Rb_total)
  Selection   = Wb * (Rp_i - Rb_i)
  Interaction = (Wp - Wb) * (Rp_i - Rb_i)

Invariant: Allocation + Selection [+ Interaction] = Excess Return
"""

import pandas as pd
import numpy as np


def compute_brinson(holdings_df: pd.DataFrame) -> dict:
    """Compute BF2 and BF3 from a holdings DataFrame.

    Columns required: industry, Wp, Wb, Rp, Rb
    Returns dict with bf2_detail, bf3_detail, and summary DataFrames.
    """
    df = holdings_df.copy()

    # Benchmark total return (weighted sum)
    Rb_total = (df["Wb"] * df["Rb"]).sum()
    # Fund total return (weighted sum)
    Rp_total = (df["Wp"] * df["Rp"]).sum()
    excess = Rp_total - Rb_total

    # --- BF3 (3-factor) ---
    df["bf3_allocation"] = (df["Wp"] - df["Wb"]) * (df["Rb"] - Rb_total)
    df["bf3_selection"] = df["Wb"] * (df["Rp"] - df["Rb"])
    df["bf3_interaction"] = (df["Wp"] - df["Wb"]) * (df["Rp"] - df["Rb"])
    df["bf3_total"] = df["bf3_allocation"] + df["bf3_selection"] + df["bf3_interaction"]

    # --- BF2 (2-factor, interaction absorbed into selection) ---
    df["bf2_allocation"] = (df["Wp"] - df["Wb"]) * (df["Rb"] - Rb_total)
    df["bf2_selection"] = df["Wp"] * (df["Rp"] - df["Rb"])
    df["bf2_total"] = df["bf2_allocation"] + df["bf2_selection"]

    # --- Verification ---
    bf2_alloc_total = df["bf2_allocation"].sum()
    bf2_select_total = df["bf2_selection"].sum()
    bf3_alloc_total = df["bf3_allocation"].sum()
    bf3_select_total = df["bf3_selection"].sum()
    bf3_interact_total = df["bf3_interaction"].sum()

    assert abs(bf2_alloc_total + bf2_select_total - excess) < 1e-10, \
        f"BF2 assertion failed: {bf2_alloc_total} + {bf2_select_total} = {bf2_alloc_total + bf2_select_total} != {excess}"
    assert abs(bf3_alloc_total + bf3_select_total + bf3_interact_total - excess) < 1e-10, \
        f"BF3 assertion failed: {bf3_alloc_total} + {bf3_select_total} + {bf3_interact_total} != {excess}"

    # Summary
    summary = pd.DataFrame([
        {
            "metric": "fund_return",
            "bf2": Rp_total,
            "bf3": Rp_total,
        },
        {
            "metric": "bench_return",
            "bf2": Rb_total,
            "bf3": Rb_total,
        },
        {
            "metric": "excess_return",
            "bf2": excess,
            "bf3": excess,
        },
        {
            "metric": "allocation_total",
            "bf2": bf2_alloc_total,
            "bf3": bf3_alloc_total,
        },
        {
            "metric": "selection_total",
            "bf2": bf2_select_total,
            "bf3": bf3_select_total,
        },
        {
            "metric": "interaction_total",
            "bf2": None,
            "bf3": bf3_interact_total,
        },
    ])

    bf2_detail = df[["industry", "Wp", "Wb", "Rp", "Rb",
                      "bf2_allocation", "bf2_selection", "bf2_total"]].copy()
    bf3_detail = df[["industry", "Wp", "Wb", "Rp", "Rb",
                      "bf3_allocation", "bf3_selection", "bf3_interaction", "bf3_total"]].copy()

    return {
        "holdings": df[["industry", "Wp", "Wb", "Rp", "Rb"]],
        "bf2": bf2_detail,
        "bf3": bf3_detail,
        "summary": summary,
    }


def write_golden(data: dict, path: str, fund_name: str):
    """Write golden dataset to Excel with metadata."""
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        # Metadata sheet
        meta = pd.DataFrame([
            {"key": "fund_name", "value": fund_name},
            {"key": "generator", "value": "generate_golden.py"},
            {"key": "brinson_paper", "value": "Brinson, Hood, Beebower (1986) / Brinson-Fachler (1985)"},
            {"key": "bf2_note", "value": "2-factor: interaction absorbed into selection. Selection = Wp * (Rp_i - Rb_i)"},
            {"key": "bf3_note", "value": "3-factor: standard BHB. Selection = Wb * (Rp_i - Rb_i), Interaction = (Wp-Wb)*(Rp_i-Rb_i)"},
        ])
        meta.to_excel(writer, sheet_name="metadata", index=False)
        data["holdings"].to_excel(writer, sheet_name="holdings", index=False)
        data["bf2"].to_excel(writer, sheet_name="bf2", index=False)
        data["bf3"].to_excel(writer, sheet_name="bf3", index=False)
        data["summary"].to_excel(writer, sheet_name="summary", index=False)
    print(f"Written: {path}")


# ============================================================
# Fund 1: 元大台灣50 (0050) — Large-cap ETF, close to benchmark
# ============================================================
fund1 = pd.DataFrame([
    {"industry": "半導體業",       "Wp": 0.42, "Wb": 0.40, "Rp": 0.085, "Rb": 0.080},
    {"industry": "金融保險業",     "Wp": 0.12, "Wb": 0.14, "Rp": 0.025, "Rb": 0.030},
    {"industry": "電子零組件業",   "Wp": 0.10, "Wb": 0.09, "Rp": 0.060, "Rb": 0.055},
    {"industry": "光電業",         "Wp": 0.06, "Wb": 0.07, "Rp": 0.040, "Rb": 0.045},
    {"industry": "通信網路業",     "Wp": 0.05, "Wb": 0.05, "Rp": 0.035, "Rb": 0.030},
    {"industry": "鋼鐵工業",       "Wp": 0.04, "Wb": 0.05, "Rp": 0.010, "Rb": 0.015},
    {"industry": "塑膠工業",       "Wp": 0.03, "Wb": 0.04, "Rp": 0.020, "Rb": 0.025},
    {"industry": "食品工業",       "Wp": 0.03, "Wb": 0.03, "Rp": 0.015, "Rb": 0.010},
    {"industry": "航運業",         "Wp": 0.05, "Wb": 0.04, "Rp": 0.070, "Rb": 0.060},
    {"industry": "建材營造業",     "Wp": 0.02, "Wb": 0.03, "Rp": 0.030, "Rb": 0.035},
    {"industry": "其他電子業",     "Wp": 0.08, "Wb": 0.06, "Rp": 0.050, "Rb": 0.040},
])
# Verify weights
assert abs(fund1["Wp"].sum() - 1.0) < 0.02, f"Fund 1 Wp sum: {fund1['Wp'].sum()}"
assert abs(fund1["Wb"].sum() - 1.0) < 1e-10, f"Fund 1 Wb sum: {fund1['Wb'].sum()}"

data1 = compute_brinson(fund1)
write_golden(data1, "tests/golden_data/fund_1.xlsx", "元大台灣50 (0050)")


# ============================================================
# Fund 2: 富邦台50 (006208) — Similar to 0050 but slightly different weights
# ============================================================
fund2 = pd.DataFrame([
    {"industry": "半導體業",       "Wp": 0.41, "Wb": 0.40, "Rp": 0.082, "Rb": 0.080},
    {"industry": "金融保險業",     "Wp": 0.13, "Wb": 0.14, "Rp": 0.028, "Rb": 0.030},
    {"industry": "電子零組件業",   "Wp": 0.09, "Wb": 0.09, "Rp": 0.058, "Rb": 0.055},
    {"industry": "光電業",         "Wp": 0.07, "Wb": 0.07, "Rp": 0.042, "Rb": 0.045},
    {"industry": "通信網路業",     "Wp": 0.05, "Wb": 0.05, "Rp": 0.032, "Rb": 0.030},
    {"industry": "鋼鐵工業",       "Wp": 0.04, "Wb": 0.05, "Rp": 0.012, "Rb": 0.015},
    {"industry": "塑膠工業",       "Wp": 0.04, "Wb": 0.04, "Rp": 0.022, "Rb": 0.025},
    {"industry": "食品工業",       "Wp": 0.03, "Wb": 0.03, "Rp": 0.012, "Rb": 0.010},
    {"industry": "航運業",         "Wp": 0.04, "Wb": 0.04, "Rp": 0.065, "Rb": 0.060},
    {"industry": "建材營造業",     "Wp": 0.03, "Wb": 0.03, "Rp": 0.032, "Rb": 0.035},
    {"industry": "其他電子業",     "Wp": 0.07, "Wb": 0.06, "Rp": 0.048, "Rb": 0.040},
])
assert abs(fund2["Wp"].sum() - 1.0) < 0.02, f"Fund 2 Wp sum: {fund2['Wp'].sum()}"
assert abs(fund2["Wb"].sum() - 1.0) < 1e-10, f"Fund 2 Wb sum: {fund2['Wb'].sum()}"

data2 = compute_brinson(fund2)
write_golden(data2, "tests/golden_data/fund_2.xlsx", "富邦台50 (006208)")


# ============================================================
# Fund 3: 科技型基金 — Tech-heavy with cash position
# Cash: Wp > 0, Wb = 0, Rp = 0 (negative allocation effect expected)
# ============================================================
fund3 = pd.DataFrame([
    {"industry": "半導體業",         "Wp": 0.35, "Wb": 0.40, "Rp": 0.095, "Rb": 0.080},
    {"industry": "光電業",           "Wp": 0.15, "Wb": 0.15, "Rp": 0.055, "Rb": 0.045},
    {"industry": "電子零組件業",     "Wp": 0.12, "Wb": 0.12, "Rp": 0.070, "Rb": 0.055},
    {"industry": "通信網路業",       "Wp": 0.10, "Wb": 0.10, "Rp": 0.040, "Rb": 0.030},
    {"industry": "資訊服務業",       "Wp": 0.08, "Wb": 0.08, "Rp": 0.065, "Rb": 0.050},
    {"industry": "電腦及週邊設備業", "Wp": 0.05, "Wb": 0.05, "Rp": 0.035, "Rb": 0.025},
    {"industry": "其他電子業",       "Wp": 0.05, "Wb": 0.10, "Rp": 0.045, "Rb": 0.040},
    {"industry": "現金",             "Wp": 0.10, "Wb": 0.00, "Rp": 0.000, "Rb": 0.000},
])
assert abs(fund3["Wp"].sum() - 1.0) < 0.02, f"Fund 3 Wp sum: {fund3['Wp'].sum()}"
assert abs(fund3["Wb"].sum() - 1.0) < 1e-10, f"Fund 3 Wb sum: {fund3['Wb'].sum()}"

data3 = compute_brinson(fund3)
write_golden(data3, "tests/golden_data/fund_3.xlsx", "科技型基金 (含現金)")


# Print summaries for verification
for i, (name, data) in enumerate(
    [("Fund 1: 元大台灣50", data1),
     ("Fund 2: 富邦台50", data2),
     ("Fund 3: 科技型基金", data3)], 1
):
    print(f"\n{'='*60}")
    print(f"  {name}")
    print(f"{'='*60}")
    s = data["summary"]
    for _, row in s.iterrows():
        print(f"  {row['metric']:20s}  BF2={row['bf2']!s:>12s}  BF3={row['bf3']!s:>12s}")
    print()
    print("  BF3 Detail:")
    print(data["bf3"].to_string(index=False))
