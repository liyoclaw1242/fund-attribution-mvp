"""Monte Carlo fan chart generator.

Renders a probability fan chart showing P10/Median/P90 projection paths
with shaded bands. Used for Goal Tracker visualization.
180 DPI, white background, CJK font for Chinese labels.
"""

from pathlib import Path
from typing import Optional

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
import numpy as np

from config.settings import CHART_DPI

# Find best CJK font
_CJK_FONTS = ["Noto Sans CJK TC", "Heiti TC", "Hiragino Sans", "Arial Unicode MS"]
CJK_FONT = None
for name in _CJK_FONTS:
    if any(f.name == name for f in fm.fontManager.ttflist):
        CJK_FONT = name
        break

if CJK_FONT:
    plt.rcParams["font.family"] = CJK_FONT
plt.rcParams["axes.unicode_minus"] = False

# Colors matching app theme
_PURPLE = "#534AB7"
_PURPLE_LIGHT = "#8B83D4"
_GREEN = "#1D9E75"
_RED = "#E24B4A"
_AMBER = "#BA7517"


def generate_fan_chart(
    years: list[int],
    p10: list[float],
    median: list[float],
    p90: list[float],
    target_amount: float,
    output_path: Optional[str | Path] = None,
) -> plt.Figure:
    """Generate a Monte Carlo fan chart.

    Args:
        years: List of year labels (e.g. [2026, 2027, ..., 2045]).
        p10: Pessimistic path values (TWD).
        median: Median path values (TWD).
        p90: Optimistic path values (TWD).
        target_amount: Target goal amount (TWD), shown as dashed line.
        output_path: If provided, saves PNG to this path.

    Returns:
        matplotlib Figure.
    """
    fig, ax = plt.subplots(figsize=(10, 5), facecolor="white")
    ax.set_facecolor("white")

    x = np.arange(len(years))

    # Shaded bands
    ax.fill_between(x, p10, p90, alpha=0.15, color=_PURPLE, label="P10–P90 區間")
    ax.fill_between(x, p10, median, alpha=0.10, color=_PURPLE)

    # Lines
    ax.plot(x, p90, color=_GREEN, linewidth=1.5, label=f"樂觀 P90", alpha=0.8)
    ax.plot(x, median, color=_PURPLE, linewidth=2.5, label="中位數 P50")
    ax.plot(x, p10, color=_RED, linewidth=1.5, label=f"悲觀 P10", alpha=0.8)

    # Target line
    ax.axhline(
        y=target_amount, color=_AMBER, linestyle="--", linewidth=1.5,
        label=f"目標 {target_amount / 10_000:,.0f} 萬",
    )

    # Formatting
    ax.set_xticks(x[::max(1, len(x) // 8)])
    ax.set_xticklabels([str(years[i]) for i in range(0, len(years), max(1, len(years) // 8))], fontsize=9)
    ax.set_ylabel("資產價值 (萬元)", fontsize=10)
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{v / 10_000:,.0f}"))

    ax.set_title("資產成長預測", fontsize=13, fontweight="bold", pad=15)
    ax.legend(loc="upper left", fontsize=9, framealpha=0.9)

    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.grid(axis="y", alpha=0.3, linewidth=0.5)

    plt.tight_layout()

    if output_path:
        fig.savefig(output_path, dpi=CHART_DPI, bbox_inches="tight", facecolor="white")

    return fig
