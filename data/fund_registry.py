"""Fund code → company mapping registry.

Hardcoded registry of popular Taiwan ETFs and mutual funds.
Maps fund_code → (company_code, fund_name, company_name, fund_type).

Future: auto-update from SITCA DR classification download.
"""

from typing import Optional

# Popular ETFs and active funds
FUND_REGISTRY = {
    # ETFs — 元大投信
    "0050": {"fund_name": "元大台灣卓越50基金", "company_code": "A0005", "company_name": "元大投信", "fund_type": "AD1"},
    "0051": {"fund_name": "元大台灣中型100基金", "company_code": "A0005", "company_name": "元大投信", "fund_type": "AD1"},
    "0052": {"fund_name": "元大台灣富櫃50基金", "company_code": "A0005", "company_name": "元大投信", "fund_type": "AD1"},
    "0056": {"fund_name": "元大高股息基金", "company_code": "A0005", "company_name": "元大投信", "fund_type": "AD1"},
    "00878": {"fund_name": "國泰永續高股息ETF", "company_code": "A0015", "company_name": "國泰投信", "fund_type": "AD1"},
    "00713": {"fund_name": "元大台灣高息低波ETF", "company_code": "A0005", "company_name": "元大投信", "fund_type": "AD1"},
    "00881": {"fund_name": "國泰台灣5G+ ETF", "company_code": "A0015", "company_name": "國泰投信", "fund_type": "AD1"},
    "00885": {"fund_name": "富邦越南ETF", "company_code": "A0010", "company_name": "富邦投信", "fund_type": "AD1"},
    "00919": {"fund_name": "群益台灣精選高息ETF", "company_code": "A0025", "company_name": "群益投信", "fund_type": "AD1"},
    "00929": {"fund_name": "復華台灣科技優息ETF", "company_code": "A0035", "company_name": "復華投信", "fund_type": "AD1"},
    "006208": {"fund_name": "富邦台50ETF", "company_code": "A0010", "company_name": "富邦投信", "fund_type": "AD1"},

    # Active funds — 國內股票型
    "YUANTA_TW50": {"fund_name": "元大台灣50基金", "company_code": "A0005", "company_name": "元大投信", "fund_type": "AA1"},
    "CATHAY_TECH": {"fund_name": "國泰科技生化基金", "company_code": "A0015", "company_name": "國泰投信", "fund_type": "AA1"},
    "FUBON_TW": {"fund_name": "富邦台灣科技指數基金", "company_code": "A0010", "company_name": "富邦投信", "fund_type": "AA1"},
    "CTBC_GROWTH": {"fund_name": "中信台灣活力基金", "company_code": "A0020", "company_name": "中國信託投信", "fund_type": "AA1"},
    "CAPITAL_TECH": {"fund_name": "群益創新科技基金", "company_code": "A0025", "company_name": "群益投信", "fund_type": "AA1"},
    "UPAMC_GROWTH": {"fund_name": "統一黑馬基金", "company_code": "A0030", "company_name": "統一投信", "fund_type": "AA1"},
    "SINOPAC_TW": {"fund_name": "永豐台灣加權ETF基金", "company_code": "A0075", "company_name": "永豐投信", "fund_type": "AD1"},
    "FIRSTBANK_TW": {"fund_name": "第一金電子科技基金", "company_code": "A0065", "company_name": "第一金投信", "fund_type": "AA1"},
    "TAISHIN_SEMI": {"fund_name": "台新台灣中小基金", "company_code": "A0070", "company_name": "台新投信", "fund_type": "AA1"},
}


def get_fund_info(fund_code: str) -> Optional[dict]:
    """Look up fund info by code.

    Args:
        fund_code: Fund code (e.g. "0050", "00878").

    Returns:
        Dict with fund_code, fund_name, company_code, company_name, fund_type.
        None if not found.
    """
    fund_code = fund_code.strip().upper()

    entry = FUND_REGISTRY.get(fund_code)
    if entry is None:
        # Try without leading zeros
        stripped = fund_code.lstrip("0")
        for code, info in FUND_REGISTRY.items():
            if code.lstrip("0") == stripped:
                entry = info
                fund_code = code
                break

    if entry is None:
        return None

    return {
        "fund_code": fund_code,
        "fund_name": entry["fund_name"],
        "company_code": entry["company_code"],
        "company_name": entry["company_name"],
        "fund_type": entry["fund_type"],
    }


def search_funds(keyword: str) -> list[dict]:
    """Search funds by keyword in name or code.

    Args:
        keyword: Search term.

    Returns:
        List of matching fund info dicts.
    """
    keyword = keyword.strip().lower()
    results = []
    for code, info in FUND_REGISTRY.items():
        if (keyword in code.lower()
            or keyword in info["fund_name"].lower()
            or keyword in info["company_name"].lower()):
            results.append({
                "fund_code": code,
                **info,
            })
    return results


def list_all_funds() -> list[dict]:
    """List all registered funds."""
    return [
        {"fund_code": code, **info}
        for code, info in FUND_REGISTRY.items()
    ]
