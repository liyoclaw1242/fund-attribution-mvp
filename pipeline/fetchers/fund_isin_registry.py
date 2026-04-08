"""ISIN registry — mapping of common offshore fund Chinese names to ISIN codes.

Used by FinnhubFundFetcher to resolve fund names to ISINs for API lookup.
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)

# Manual mapping: Chinese fund name → ISIN code
# Covers 50+ common offshore funds sold in Taiwan
FUND_ISIN_MAP: dict[str, str] = {
    # --- JP Morgan (摩根) ---
    "摩根太平洋科技基金": "LU0117844026",
    "摩根中國基金": "LU0117838416",
    "摩根亞洲增長基金": "LU0117842095",
    "摩根日本基金": "LU0117857879",
    "摩根新興市場股票基金": "LU0117856637",
    "摩根美國科技基金": "LU0159052710",
    "摩根環球天然資源基金": "LU0208853274",
    "摩根印度基金": "LU0210527791",
    "摩根歐洲基金": "LU0117854330",
    "摩根全球品牌基金": "LU0119066131",
    # --- Allianz (安聯) ---
    "安聯收益成長基金-AM穩定月收類股": "LU0689472784",
    "安聯收益成長基金-AT累積類股": "LU0689473162",
    "安聯台灣科技基金": "LU0348404012",
    "安聯歐洲高息股票基金": "LU0165251603",
    "安聯美國短年期高收益債券基金": "LU1040968498",
    "安聯全球人工智慧基金": "LU1548497699",
    # --- Fidelity (富達) ---
    "富達亞洲高收益基金": "LU0286668966",
    "富達全球科技基金": "LU1046421795",
    "富達新興市場基金": "LU0048575426",
    "富達歐洲基金": "LU0048578792",
    "富達中國聚焦基金": "LU0318931358",
    "富達全球股息基金": "LU0772969993",
    # --- BlackRock (貝萊德) ---
    "貝萊德世界科技基金": "LU0171310443",
    "貝萊德全球資產配置基金": "LU0093503810",
    "貝萊德世界礦業基金": "LU0172157280",
    "貝萊德亞洲龍頭企業基金": "LU0821914370",
    "貝萊德環球動力股票基金": "LU0171289902",
    "貝萊德世界健康科學基金": "LU0171307266",
    # --- Franklin Templeton (富蘭克林坦伯頓) ---
    "富蘭克林坦伯頓成長基金": "LU0316494731",
    "富蘭克林坦伯頓全球債券基金": "LU0252652382",
    "富蘭克林科技基金": "US3536852073",
    "富蘭克林坦伯頓新興國家基金": "LU0229946898",
    "富蘭克林公用事業基金": "US3537921085",
    "富蘭克林高科技基金": "LU0109392836",
    # --- Invesco (景順) ---
    "景順全球消費趨勢基金": "LU1762220050",
    "景順亞洲機會基金": "IE0030381945",
    "景順日本基金": "IE0030382166",
    # --- Schroders (施羅德) ---
    "施羅德環球債券收益基金": "LU0106236184",
    "施羅德亞洲高息股債基金": "LU0995120168",
    "施羅德環球新興市場基金": "LU0106252546",
    # --- PIMCO ---
    "PIMCO全球高收益債券基金": "IE00B11XZ541",
    "PIMCO總回報債券基金": "IE00B11XZ210",
    "PIMCO新興市場債券基金": "IE00B11XZB05",
    # --- AB (聯博) ---
    "聯博全球高收益債券基金": "LU0102830865",
    "聯博美國收益基金": "LU0511384066",
    "聯博美國成長基金": "LU0079474960",
    # --- Others ---
    "鋒裕匯理基金-歐元高收益債券": "LU0119110962",
    "百達環球精選基金": "LU0130728842",
    "野村全球品牌基金": "IE00B0H1R063",
    "柏瑞環球關鍵趨勢基金": "IE0004866889",
}

# Reverse map: ISIN → fund name
_ISIN_TO_NAME = {v: k for k, v in FUND_ISIN_MAP.items()}


def lookup_isin(fund_name: str) -> Optional[str]:
    """Look up ISIN code for a fund by Chinese name.

    Tries exact match first, then contains match.

    Args:
        fund_name: Fund name in Chinese.

    Returns:
        ISIN code or None.
    """
    # Exact match
    if fund_name in FUND_ISIN_MAP:
        return FUND_ISIN_MAP[fund_name]

    # Contains match
    for name, isin in FUND_ISIN_MAP.items():
        if fund_name in name or name in fund_name:
            return isin

    return None


def lookup_name(isin: str) -> Optional[str]:
    """Reverse lookup: ISIN → fund name."""
    return _ISIN_TO_NAME.get(isin)


def get_all_isins() -> list[str]:
    """Return all registered ISIN codes."""
    return list(FUND_ISIN_MAP.values())
