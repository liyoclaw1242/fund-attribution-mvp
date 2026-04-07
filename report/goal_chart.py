"""Monte Carlo fan chart for goal tracking.

Shows p10/median/p90 wealth paths over time, with target line.
"""

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
import numpy as np

from config.settings import CHART_DPI

# CJK font detection (same pattern as waterfall.py)
_CJK_FONTS = ["Noto Sans CJK TC", "Heiti TC", "Hiragino Sans", "Arial Unicode MS"]
CJK_FONT = None
for name in _CJK_FONTS:
    if any(f.name == name for f in fm.fontManager.ttflist):
        CJK_FONT = name
        break

if CJK_FONT:
    plt.rcParams["font.family"] = CJK_FONT
plt.rcParams["axes.unicode_minus"] = False

MONTHS_PER_YEAR = 12

RETURN_ASSUMPTIONS = {
    "conservative": {"mean": 0.04, "std": 0.05},
    "moderate":     {"mean": 0.07, "std": 0.12},
    "aggressive":   {"mean": 0.10, "std": 0.18},
}


def _simulate_full_paths(
    initial_balance: float,
    monthly_contribution: float,
    risk_tolerance: str,
    years: int,
    num_paths: int = 500,
    seed: int = 42,
) -> np.ndarray:
    """Simulate full wealth paths (yearly snapshots).

    Returns:
        Array of shape (num_paths, years+1) with yearly wealth values.
    """
    assumptions = RETURN_ASSUMPTIONS[risk_tolerance.lower()]
    monthly_mean = assumptions["mean"] / MONTHS_PER_YEAR
    monthly_std = assumptions["std"] / np.sqrt(MONTHS_PER_YEAR)

    rng = np.random.default_rng(seed)
    total_months = years * MONTHS_PER_YEAR

    # Generate all returns
    monthly_returns = rng.normal(monthly_mean, monthly_std, (num_paths, total_months))

    # Track yearly snapshots
    yearly = np.zeros((num_paths, years + 1))
    balances = np.full(num_paths, initial_balance, dtype=np.float64)
    yearly[:, 0] = balances

    for year in range(years):
        for month in range(MONTHS_PER_YEAR):
            m = year * MONTHS_PER_YEAR + month
            balances = balances * (1 + monthly_returns[:, m]) + monthly_contribution
        balances = np.maximum(balances, 0)
        yearly[:, year + 1] = balances

    return yearly


def generate_goal_chart(
    initial_balance: float,
    monthly_contribution: float,
    risk_tolerance: str,
    years: int,
    target_amount: float,
    success_probability: float,
) -> plt.Figure:
    """Generate Monte Carlo fan chart for goal tracking.

    Args:
        initial_balance: Starting savings (TWD).
        monthly_contribution: Monthly investment (TWD).
        risk_tolerance: conservative/moderate/aggressive.
        years: Years to goal.
        target_amount: Goal target (TWD).
        success_probability: Pre-calculated success probability.

    Returns:
        matplotlib Figure.
    """
    import datetime
    current_year = datetime.datetime.now().year
    year_labels = list(range(current_year, current_year + years + 1))

    paths = _simulate_full_paths(
        initial_balance=initial_balance,
        monthly_contribution=monthly_contribution,
        risk_tolerance=risk_tolerance,
        years=years,
    )

    # Percentiles at each year
    p10 = np.percentile(paths, 10, axis=0)
    p25 = np.percentile(paths, 25, axis=0)
    p50 = np.percentile(paths, 50, axis=0)
    p75 = np.percentile(paths, 75, axis=0)
    p90 = np.percentile(paths, 90, axis=0)

    t = np.arange(years + 1)

    fig, ax = plt.subplots(figsize=(10, 5.5), facecolor="white")
    ax.set_facecolor("white")

    # Fan bands
    ax.fill_between(year_labels, p10, p90, alpha=0.12, color="#534AB7", label="P10–P90 範圍")
    ax.fill_between(year_labels, p25, p75, alpha=0.20, color="#534AB7", label="P25–P75 範圍")

    # Median line
    ax.plot(year_labels, p50, color="#534AB7", linewidth=2.5, label="中位數 (P50)")

    # Target line
    ax.axhline(y=target_amount, color="#E24B4A", linestyle="--", linewidth=1.5, label=f"目標 NT${target_amount:,.0f}")

    # Annotate final percentiles
    for pct, val, label in [(p10, p10[-1], "P10"), (p50, p50[-1], "P50"), (p90, p90[-1], "P90")]:
        ax.annotate(
            f"{label}: ${val:,.0f}",
            xy=(year_labels[-1], val),
            xytext=(8, 0),
            textcoords="offset points",
            fontsize=8,
            color="#534AB7",
            va="center",
        )

    # Labels
    ax.set_xlabel("年", fontsize=11)
    ax.set_ylabel("預估資產 (TWD)", fontsize=11)

    risk_labels = {"conservative": "保守型", "moderate": "穩健型", "aggressive": "積極型"}
    risk_label = risk_labels.get(risk_tolerance.lower(), risk_tolerance)

    ax.set_title(
        f"Monte Carlo 模擬 — {risk_label}投資組合（{success_probability:.0%} 達標機率）",
        fontsize=13, fontweight="bold", pad=15,
    )

    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"${v:,.0f}"))
    ax.legend(loc="upper left", fontsize=9, framealpha=0.9)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.grid(axis="y", alpha=0.3)

    plt.tight_layout()
    return fig
