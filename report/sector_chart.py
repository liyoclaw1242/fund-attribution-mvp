"""Sector contribution horizontal bar chart.

Sorted by total contribution.
Green (#1D9E75) for positive, Red (#E24B4A) for negative.
180 DPI, CJK font, auto-scaled.
"""

from pathlib import Path
from typing import Optional

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from config.settings import CHART_DPI, COLORS

# Import CJK font config from waterfall module
from report.waterfall import CJK_FONT
if CJK_FONT:
    plt.rcParams["font.family"] = CJK_FONT
plt.rcParams["axes.unicode_minus"] = False


def generate_sector_chart(
    result: dict,
    output_path: Optional[str | Path] = None,
) -> plt.Figure:
    """Generate a horizontal bar chart of sector contributions.

    Args:
        result: AttributionResult dict with 'detail' DataFrame.
        output_path: If provided, saves PNG to this path.

    Returns:
        matplotlib Figure.
    """
    detail = result["detail"].copy()

    # Sort by total_contrib
    detail = detail.sort_values("total_contrib", ascending=True).reset_index(drop=True)

    industries = detail["industry"].tolist()
    contributions = detail["total_contrib"].tolist()
    bar_colors = [
        COLORS["positive"] if v >= 0 else COLORS["negative"]
        for v in contributions
    ]

    # Figure height scales with number of industries
    fig_height = max(4, len(industries) * 0.45 + 1)
    fig, ax = plt.subplots(figsize=(8, fig_height), facecolor="white")
    ax.set_facecolor("white")

    y = range(len(industries))
    bars = ax.barh(y, contributions, color=bar_colors, edgecolor="white", height=0.6)

    # Value labels
    for i, (bar, val) in enumerate(zip(bars, contributions)):
        label = f"{val * 100:+.2f}%"
        x_pos = val + (max(abs(v) for v in contributions) * 0.03) * (1 if val >= 0 else -1)
        ha = "left" if val >= 0 else "right"
        ax.text(x_pos, i, label, ha=ha, va="center", fontsize=8, fontweight="bold")

    ax.set_yticks(y)
    ax.set_yticklabels(industries, fontsize=9)
    ax.xaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{v * 100:.2f}%"))
    ax.axvline(x=0, color="#DDDDDD", linewidth=0.5)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)

    ax.set_title("產業貢獻分析", fontsize=13, fontweight="bold", pad=15)
    ax.set_xlabel("總貢獻", fontsize=10)

    plt.tight_layout()

    if output_path:
        fig.savefig(output_path, dpi=CHART_DPI, bbox_inches="tight", facecolor="white")

    return fig
