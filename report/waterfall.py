"""Waterfall chart generator.

BF2: 4 bars (Benchmark, Allocation, Selection, Fund Total)
BF3: 5 bars (+ Interaction)
Floating middle bars, dashed connectors, value labels above bars.
180 DPI, white background, CJK font for Chinese labels.
Auto-scaled Y axis.
"""

from pathlib import Path
from typing import Optional

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm

from config.settings import CHART_DPI, COLORS

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


def generate_waterfall(
    result: dict,
    output_path: Optional[str | Path] = None,
) -> plt.Figure:
    """Generate a waterfall chart from AttributionResult.

    Args:
        result: AttributionResult dict.
        output_path: If provided, saves PNG to this path.

    Returns:
        matplotlib Figure.
    """
    mode = result.get("brinson_mode", "BF2")

    # Build bar data
    labels = ["基準報酬"]
    values = [result["bench_return"]]
    colors = [COLORS["benchmark"]]

    labels.append("產業配置")
    values.append(result["allocation_total"])
    colors.append(COLORS["allocation"])

    labels.append("選股能力")
    values.append(result["selection_total"])
    colors.append(COLORS["selection"])

    if mode == "BF3" and result.get("interaction_total") is not None:
        labels.append("交互效果")
        values.append(result["interaction_total"])
        colors.append(COLORS["interaction"])

    labels.append("基金報酬")
    values.append(result["fund_return"])
    colors.append(COLORS["fund_total"])

    # Compute waterfall positions
    n = len(labels)
    bottoms = [0.0] * n
    heights = list(values)

    # First bar starts at 0
    bottoms[0] = 0.0

    # Middle bars float: bottom = cumulative sum up to that point
    cumulative = values[0]
    for i in range(1, n - 1):
        if values[i] >= 0:
            bottoms[i] = cumulative
        else:
            bottoms[i] = cumulative + values[i]
            heights[i] = abs(values[i])
        cumulative += values[i]

    # Last bar (Fund Total) starts at 0
    bottoms[-1] = 0.0
    heights[-1] = values[-1]

    # Create figure
    fig, ax = plt.subplots(figsize=(8, 5), facecolor="white")
    ax.set_facecolor("white")

    x = range(n)
    bar_width = 0.6

    # Draw bars
    bars = ax.bar(x, heights, bottom=bottoms, width=bar_width, color=colors, edgecolor="white", linewidth=0.5)

    # Dashed connectors between floating bars
    for i in range(n - 1):
        top_i = bottoms[i] + heights[i] if values[i] >= 0 else bottoms[i]
        if i == 0:
            top_i = values[0]
        connector_y = cumulative_at(values, i)
        ax.plot(
            [i + bar_width / 2, i + 1 - bar_width / 2],
            [connector_y, connector_y],
            color="#CCCCCC", linestyle="--", linewidth=0.8,
        )

    # Value labels
    for i, (bar, val) in enumerate(zip(bars, values)):
        label = f"{val * 100:+.2f}%" if i > 0 and i < n - 1 else f"{val * 100:.2f}%"
        y_pos = bottoms[i] + heights[i] + (max(abs(v) for v in values) * 0.02)
        ax.text(
            i, y_pos, label,
            ha="center", va="bottom", fontsize=9, fontweight="bold",
            color=colors[i],
        )

    ax.set_xticks(x)
    ax.set_xticklabels(labels, fontsize=10)
    ax.set_ylabel("報酬率", fontsize=10)
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{v * 100:.1f}%"))
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.axhline(y=0, color="#DDDDDD", linewidth=0.5)

    title = "歸因分析瀑布圖" + (f" ({mode})" if mode else "")
    ax.set_title(title, fontsize=13, fontweight="bold", pad=15)

    plt.tight_layout()

    if output_path:
        fig.savefig(output_path, dpi=CHART_DPI, bbox_inches="tight", facecolor="white")

    return fig


def cumulative_at(values: list[float], index: int) -> float:
    """Cumulative sum of values up to and including index."""
    return sum(values[:index + 1])
