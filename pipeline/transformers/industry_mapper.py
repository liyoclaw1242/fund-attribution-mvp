"""Unified industry mapper — normalize industry names across all data sources.

Maps TSE 28 categories, GICS sectors, and FinMind categories to a unified
industry name. Extends the existing data/mapping.json logic for pipeline use.
"""

import json
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Load the existing mapping from data/mapping.json
_MAPPING_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "mapping.json"

# TWSE index name → unified industry (strip "類指數" suffix)
_TWSE_INDEX_STRIP = {"類指數", "指數"}

# GICS → Traditional Chinese unified name
GICS_TO_UNIFIED = {
    "Technology": "資訊科技",
    "Information Technology": "資訊科技",
    "Healthcare": "醫療保健",
    "Health Care": "醫療保健",
    "Financial Services": "金融保險業",
    "Financials": "金融保險業",
    "Consumer Cyclical": "非必需消費",
    "Consumer Discretionary": "非必需消費",
    "Communication Services": "通信網路業",
    "Industrials": "電機機械",
    "Consumer Defensive": "必需消費",
    "Consumer Staples": "必需消費",
    "Energy": "油電燃氣業",
    "Utilities": "公用事業",
    "Real Estate": "不動產",
    "Basic Materials": "化學工業",
    "Materials": "化學工業",
}


# Finnhub sector names → unified Chinese (Finnhub uses different labels than GICS)
FINNHUB_SECTOR_MAP = {
    "Technology": "資訊科技",
    "Financial Services": "金融",
    "Healthcare": "醫療保健",
    "Consumer Cyclical": "消費循環",
    "Industrials": "工業",
    "Communication Services": "通訊服務",
    "Consumer Defensive": "消費必需",
    "Energy": "能源",
    "Utilities": "公用事業",
    "Real Estate": "不動產",
    "Basic Materials": "原物料",
    "Financial": "金融",
    "Bonds": "債券",
    "Cash": "現金",
    "Other": "其他",
    "Unknown": "未分類",
}


def load_mapping(path: Path | str | None = None) -> dict[str, str]:
    """Load the SITCA→TSE 28 mapping from JSON.

    Returns:
        Dict {source_name: unified_name}.
    """
    p = Path(path) if path else _MAPPING_PATH
    if not p.exists():
        logger.warning("Mapping file not found: %s — using empty mapping", p)
        return {}

    with open(p, encoding="utf-8") as f:
        data = json.load(f)

    return {k: v for k, v in data.items() if not k.startswith("_")}


# Module-level cache
_mapping_cache: dict[str, str] | None = None


def _get_mapping() -> dict[str, str]:
    global _mapping_cache
    if _mapping_cache is None:
        _mapping_cache = load_mapping()
    return _mapping_cache


def map_industry(raw_name: str, source: str = "auto") -> Optional[str]:
    """Map a raw industry name to the unified taxonomy.

    Args:
        raw_name: Industry name from any source.
        source: Hint — 'tse28', 'gics', 'finmind', 'sitca', or 'auto'.

    Returns:
        Unified industry name, or None if unmapped.
    """
    if not raw_name or not raw_name.strip():
        return None

    raw_name = raw_name.strip()

    # 1a. Finnhub sector mapping
    if source in ("finnhub", "auto"):
        finnhub_match = FINNHUB_SECTOR_MAP.get(raw_name)
        if finnhub_match:
            return finnhub_match

    # 1b. GICS mapping (English sources)
    if source in ("gics", "auto"):
        gics_match = GICS_TO_UNIFIED.get(raw_name)
        if gics_match:
            return gics_match

    # 2. SITCA / TSE 28 mapping (Chinese sources)
    mapping = _get_mapping()

    # Exact match
    if raw_name in mapping:
        return mapping[raw_name]

    # Contains match
    for key, value in mapping.items():
        if key in raw_name:
            return value

    # TWSE index suffix strip
    stripped = raw_name
    for suffix in _TWSE_INDEX_STRIP:
        stripped = stripped.replace(suffix, "")
    if stripped != raw_name and stripped in mapping:
        return mapping[stripped]

    # FinMind categories often match TSE 28 directly
    if source in ("finmind", "auto"):
        for key, value in mapping.items():
            if raw_name in key or key in raw_name:
                return value

    return None


def map_dataframe(
    df, industry_col: str = "industry", source: str = "auto"
) -> None:
    """Map industry column in-place on a DataFrame.

    Unmapped values are left as-is (not replaced with None).
    """
    if industry_col not in df.columns:
        return

    df[industry_col] = df[industry_col].apply(
        lambda x: map_industry(str(x), source) or x if pd.notna(x) else x
    )


# Import pandas lazily for map_dataframe
import pandas as pd
