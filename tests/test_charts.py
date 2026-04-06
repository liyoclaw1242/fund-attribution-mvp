"""Tests for report/waterfall.py and report/sector_chart.py."""

from pathlib import Path

import pandas as pd
import pytest

from report.waterfall import generate_waterfall
from report.sector_chart import generate_sector_chart


@pytest.fixture
def bf2_result():
    detail = pd.DataFrame([
        {"industry": "半導體業", "Wp": 0.42, "Wb": 0.40, "Rp": 0.085, "Rb": 0.080,
         "alloc_effect": 0.001, "select_effect": 0.002, "interaction_effect": 0.0, "total_contrib": 0.003},
        {"industry": "金融保險業", "Wp": 0.12, "Wb": 0.14, "Rp": 0.025, "Rb": 0.030,
         "alloc_effect": -0.0005, "select_effect": -0.0006, "interaction_effect": 0.0, "total_contrib": -0.0011},
        {"industry": "航運業", "Wp": 0.05, "Wb": 0.04, "Rp": 0.070, "Rb": 0.060,
         "alloc_effect": 0.0003, "select_effect": 0.0005, "interaction_effect": 0.0, "total_contrib": 0.0008},
    ])
    return {
        "fund_return": 0.058,
        "bench_return": 0.053,
        "excess_return": 0.005,
        "allocation_total": 0.002,
        "selection_total": 0.003,
        "interaction_total": None,
        "brinson_mode": "BF2",
        "detail": detail,
        "top_contributors": detail.nlargest(3, "total_contrib"),
        "bottom_contributors": detail.nsmallest(3, "total_contrib"),
    }


@pytest.fixture
def bf3_result(bf2_result):
    result = {**bf2_result}
    result["brinson_mode"] = "BF3"
    result["interaction_total"] = 0.001
    result["selection_total"] = 0.002
    return result


class TestWaterfallChart:
    def test_bf2_generates_figure(self, bf2_result):
        fig = generate_waterfall(bf2_result)
        assert fig is not None
        ax = fig.axes[0]
        # BF2: 4 bars
        assert len(ax.patches) == 4
        plt_close(fig)

    def test_bf3_generates_figure(self, bf3_result):
        fig = generate_waterfall(bf3_result)
        assert fig is not None
        ax = fig.axes[0]
        # BF3: 5 bars
        assert len(ax.patches) == 5
        plt_close(fig)

    def test_saves_png(self, bf2_result, tmp_path):
        path = tmp_path / "waterfall.png"
        fig = generate_waterfall(bf2_result, output_path=path)
        assert path.exists()
        assert path.stat().st_size > 1000  # non-trivial file size
        plt_close(fig)

    def test_negative_excess(self, bf2_result):
        result = {**bf2_result}
        result["allocation_total"] = -0.003
        result["selection_total"] = -0.002
        result["excess_return"] = -0.005
        result["fund_return"] = 0.048
        fig = generate_waterfall(result)
        assert fig is not None
        plt_close(fig)


class TestSectorChart:
    def test_generates_figure(self, bf2_result):
        fig = generate_sector_chart(bf2_result)
        assert fig is not None
        ax = fig.axes[0]
        assert len(ax.patches) == 3  # 3 industries
        plt_close(fig)

    def test_saves_png(self, bf2_result, tmp_path):
        path = tmp_path / "sector.png"
        fig = generate_sector_chart(bf2_result, output_path=path)
        assert path.exists()
        assert path.stat().st_size > 1000
        plt_close(fig)

    def test_sorted_by_contribution(self, bf2_result):
        fig = generate_sector_chart(bf2_result)
        ax = fig.axes[0]
        yticks = [t.get_text() for t in ax.get_yticklabels()]
        # Bottom bar should be the most negative
        assert yticks[0] == "金融保險業"
        plt_close(fig)

    def test_many_industries(self):
        detail = pd.DataFrame([
            {"industry": f"產業{i}", "total_contrib": 0.01 - i * 0.002,
             "Wp": 0.1, "Wb": 0.1, "Rp": 0.05, "Rb": 0.04,
             "alloc_effect": 0.001, "select_effect": 0.001, "interaction_effect": 0.0}
            for i in range(15)
        ])
        result = {
            "detail": detail,
            "brinson_mode": "BF2",
        }
        fig = generate_sector_chart(result)
        assert fig is not None
        plt_close(fig)


def plt_close(fig):
    import matplotlib.pyplot as plt
    plt.close(fig)
