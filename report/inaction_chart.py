"""Inaction Cost Visualizer — line chart showing purchasing power erosion.

Three scenarios over N years:
  a. Cash under mattress (inflation erosion only)
  b. Fixed deposit (nominal rate - inflation)
  c. Moderate portfolio (return - inflation)

All values shown in real (inflation-adjusted) purchasing power.
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


def generate_inaction_chart(
    cash_amount: float,
    cpi_rate: float = 0.02,
    deposit_rate: float = 0.015,
    portfolio_rate: float = 0.06,
    years: int = 10,
) -> tuple[plt.Figure, dict]:
    """Generate inaction cost line chart.

    All outputs are in real purchasing power (inflation-adjusted).

    Args:
        cash_amount: Initial TWD amount.
        cpi_rate: Annual CPI inflation rate (decimal).
        deposit_rate: Annual fixed deposit nominal rate (decimal).
        portfolio_rate: Annual portfolio nominal return (decimal).
        years: Projection horizon.

    Returns:
        (fig, summary) where summary contains final values for each scenario.
    """
    t = np.arange(0, years + 1)

    # Real (inflation-adjusted) purchasing power per year
    # Mattress: no return, pure inflation erosion
    mattress = cash_amount * (1 / (1 + cpi_rate)) ** t

    # Fixed deposit: real rate = (1 + nominal) / (1 + cpi) - 1
    real_deposit = (1 + deposit_rate) / (1 + cpi_rate) - 1
    deposit = cash_amount * (1 + real_deposit) ** t

    # Portfolio: real rate = (1 + nominal) / (1 + cpi) - 1
    real_portfolio = (1 + portfolio_rate) / (1 + cpi_rate) - 1
    portfolio = cash_amount * (1 + real_portfolio) ** t

    # Create figure
    fig, ax = plt.subplots(figsize=(10, 5), facecolor="white")
    ax.set_facecolor("white")

    ax.plot(t, mattress, color="#E24B4A", linewidth=2.5, marker="o", markersize=4,
            label="現金放床底（通膨侵蝕）")
    ax.plot(t, deposit, color="#BA7517", linewidth=2.5, marker="s", markersize=4,
            label=f"定存 ({deposit_rate * 100:.1f}%)")
    ax.plot(t, portfolio, color="#1D9E75", linewidth=2.5, marker="^", markersize=4,
            label=f"穩健投資 ({portfolio_rate * 100:.1f}%)")

    # Reference line at initial amount
    ax.axhline(y=cash_amount, color="#CCCCCC", linestyle="--", linewidth=1, label="初始金額")

    # Shade the loss area between mattress and initial
    ax.fill_between(t, mattress, cash_amount, alpha=0.08, color="#E24B4A")

    # Shade the gain area for portfolio
    ax.fill_between(t, portfolio, cash_amount, where=portfolio >= cash_amount,
                    alpha=0.08, color="#1D9E75")

    # Labels
    ax.set_xlabel("年", fontsize=11)
    ax.set_ylabel("實質購買力 (TWD)", fontsize=11)
    ax.set_title(
        f"不投資的代價 — ${cash_amount:,.0f} 的 {years} 年購買力變化",
        fontsize=13, fontweight="bold", pad=15,
    )

    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"${v:,.0f}"))
    ax.set_xticks(t)
    ax.legend(loc="best", fontsize=9, framealpha=0.9)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.grid(axis="y", alpha=0.3)

    # Annotate final values
    for series, label, color in [
        (mattress, "現金", "#E24B4A"),
        (deposit, "定存", "#BA7517"),
        (portfolio, "投資", "#1D9E75"),
    ]:
        final = series[-1]
        ax.annotate(
            f"${final:,.0f}",
            xy=(years, final),
            xytext=(5, 0),
            textcoords="offset points",
            fontsize=8,
            fontweight="bold",
            color=color,
            va="center",
        )

    plt.tight_layout()

    summary = {
        "mattress_final": float(mattress[-1]),
        "deposit_final": float(deposit[-1]),
        "portfolio_final": float(portfolio[-1]),
        "mattress_loss": float(cash_amount - mattress[-1]),
        "deposit_real_gain": float(deposit[-1] - cash_amount),
        "portfolio_real_gain": float(portfolio[-1] - cash_amount),
    }

    return fig, summary
