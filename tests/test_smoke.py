"""Production smoke test — 10 synthetic funds full pipeline within 60s.

Generates 10 synthetic holdings with varied profiles, runs each through
compute_attribution → generate_waterfall → generate_sector_chart →
generate_fallback → generate_pdf, and verifies all outputs.

Results written to smoke_test_report.md.
"""

import time
from pathlib import Path

import pandas as pd
import numpy as np
import pytest

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from engine.brinson import compute_attribution
from ai.fallback_template import generate_fallback
from report.waterfall import generate_waterfall
from report.sector_chart import generate_sector_chart
from report.pdf_generator import generate_pdf


# 10 synthetic fund profiles with different characteristics
FUND_PROFILES = [
    {"code": "FUND01", "desc": "大型均衡基金", "n": 6, "seed": 42},
    {"code": "FUND02", "desc": "科技重壓基金", "n": 4, "seed": 123},
    {"code": "FUND03", "desc": "金融主題基金", "n": 5, "seed": 456},
    {"code": "FUND04", "desc": "傳產型基金", "n": 8, "seed": 789},
    {"code": "FUND05", "desc": "小型股基金", "n": 10, "seed": 101},
    {"code": "FUND06", "desc": "高現金部位基金", "n": 3, "seed": 202},
    {"code": "FUND07", "desc": "BF3 三因子基金", "n": 6, "seed": 303},
    {"code": "FUND08", "desc": "負報酬期間基金", "n": 5, "seed": 404},
    {"code": "FUND09", "desc": "單一產業集中基金", "n": 2, "seed": 505},
    {"code": "FUND10", "desc": "多產業分散基金", "n": 15, "seed": 606},
]

INDUSTRIES = [
    "半導體業", "金融保險業", "電子零組件業", "鋼鐵工業", "塑膠工業",
    "食品工業", "紡織纖維", "電機機械", "化學工業", "水泥工業",
    "汽車工業", "營建業", "航運業", "觀光事業", "電器電纜",
]


def _generate_holdings(profile):
    """Generate synthetic holdings for a fund profile."""
    rng = np.random.RandomState(profile["seed"])
    n = min(profile["n"], len(INDUSTRIES))
    industries = INDUSTRIES[:n]

    # Generate random weights that sum to 1.0
    raw_wp = rng.dirichlet(np.ones(n))
    raw_wb = rng.dirichlet(np.ones(n))

    # Generate returns
    if profile["code"] == "FUND08":
        # Negative return period
        rp = rng.uniform(-0.15, -0.01, n)
        rb = rng.uniform(-0.10, 0.02, n)
    elif profile["code"] == "FUND06":
        # High cash: first industry is cash
        industries = ["現金"] + industries[1:]
        raw_wp[0] = 0.40
        raw_wp[1:] = raw_wp[1:] / raw_wp[1:].sum() * 0.60
        raw_wb[0] = 0.0
        raw_wb[1:] = raw_wb[1:] / raw_wb[1:].sum()
        rp = np.zeros(n)
        rp[1:] = rng.uniform(0.01, 0.15, n - 1)
        rb = np.zeros(n)
        rb[1:] = rng.uniform(0.01, 0.12, n - 1)
    else:
        rp = rng.uniform(-0.05, 0.15, n)
        rb = rng.uniform(-0.03, 0.12, n)

    return pd.DataFrame({
        "industry": industries,
        "Wp": raw_wp,
        "Wb": raw_wb,
        "Rp": rp,
        "Rb": rb,
    })


class TestSmokeFullPipeline:
    """S1: 10 synthetic funds → all produce valid reports within 60s."""

    def test_10_funds_within_60s(self, tmp_path):
        """Run 10 funds through full pipeline, all must complete within 60s."""
        start = time.time()
        results = []

        for profile in FUND_PROFILES:
            fund_start = time.time()
            mode = "BF3" if profile["code"] == "FUND07" else "BF2"

            # 1. Generate holdings
            holdings = _generate_holdings(profile)

            # 2. Compute attribution
            result = compute_attribution(holdings, mode=mode)
            assert result["fund_return"] is not None
            assert result["excess_return"] is not None

            # 3. Generate waterfall chart
            wf_path = tmp_path / f"{profile['code']}_waterfall.png"
            fig = generate_waterfall(result, output_path=str(wf_path))
            plt.close(fig)
            assert wf_path.exists()
            assert wf_path.stat().st_size > 0

            # 4. Generate sector chart
            sc_path = tmp_path / f"{profile['code']}_sector.png"
            fig = generate_sector_chart(result, output_path=str(sc_path))
            plt.close(fig)
            assert sc_path.exists()

            # 5. Generate fallback summary
            summary = generate_fallback(result)
            assert summary["line_message"]
            assert summary["pdf_summary"]
            assert summary["advisor_note"]

            # 6. Generate PDF
            pdf_path = tmp_path / f"{profile['code']}_report.pdf"
            output = generate_pdf(
                result=result,
                summary=summary,
                output_path=str(pdf_path),
                fund_code=profile["code"],
                period="2026-03",
                advisor_name="QA Agent",
                waterfall_path=str(wf_path),
                sector_chart_path=str(sc_path),
            )
            assert Path(output).exists()
            assert Path(output).stat().st_size > 0

            fund_elapsed = time.time() - fund_start
            results.append({
                "code": profile["code"],
                "desc": profile["desc"],
                "mode": mode,
                "fund_return": f"{result['fund_return'] * 100:.2f}%",
                "excess_return": f"{result['excess_return'] * 100:.2f}%",
                "pdf_size": Path(output).stat().st_size,
                "elapsed_s": f"{fund_elapsed:.2f}",
                "status": "PASS",
            })

        total_elapsed = time.time() - start
        assert total_elapsed < 60, f"Smoke test took {total_elapsed:.1f}s (limit: 60s)"

        # Write smoke test report
        report_path = tmp_path / "smoke_test_report.md"
        _write_report(report_path, results, total_elapsed)

        # Also write to project root
        project_report = Path(__file__).resolve().parent.parent / "smoke_test_report.md"
        _write_report(project_report, results, total_elapsed)


def _write_report(path, results, total_elapsed):
    lines = [
        "# Smoke Test Report",
        "",
        f"- **Date**: {time.strftime('%Y-%m-%d %H:%M:%S')}",
        f"- **Agent**: qa-20260406-0956311",
        f"- **Total Time**: {total_elapsed:.2f}s",
        f"- **Funds Tested**: {len(results)}",
        f"- **All Passed**: {'YES' if all(r['status'] == 'PASS' for r in results) else 'NO'}",
        "",
        "## Results",
        "",
        "| Fund | Description | Mode | Fund Return | Excess | PDF Size | Time | Status |",
        "|------|-------------|------|-------------|--------|----------|------|--------|",
    ]
    for r in results:
        lines.append(
            f"| {r['code']} | {r['desc']} | {r['mode']} | {r['fund_return']} | "
            f"{r['excess_return']} | {r['pdf_size']:,}B | {r['elapsed_s']}s | {r['status']} |"
        )
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")
