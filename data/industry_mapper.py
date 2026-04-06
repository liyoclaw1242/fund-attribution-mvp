"""Map SITCA raw industry categories to TSE 28 standard.

Uses ~30 hardcoded rules in mapping.json.
Match via Python 'in' operator (contains match).
NO Levenshtein / edit-distance matching.
Unmapped categories logged to unmapped_categories table.
"""

import json
import logging
from pathlib import Path
from typing import Optional

import pandas as pd

from config.settings import UNMAPPED_WARN_THRESHOLD, UNMAPPED_BLOCK_THRESHOLD

logger = logging.getLogger(__name__)

MAPPING_PATH = Path(__file__).resolve().parent / "mapping.json"


def load_mapping(path: str | Path = MAPPING_PATH) -> dict[str, str]:
    """Load industry mapping rules from JSON file.

    Returns:
        Dict of {source_name: standard_name}.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Mapping file not found: {path}")

    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    # Remove comment keys
    return {k: v for k, v in data.items() if not k.startswith("_")}


def map_industry(
    raw_name: str,
    mapping: dict[str, str],
) -> Optional[str]:
    """Map a single raw industry name to TSE 28 standard.

    Strategy:
    1. Exact match
    2. Contains match: if any mapping key is contained in the raw name
    3. Reverse contains: if raw name is contained in any mapping key

    NO fuzzy/Levenshtein matching — too dangerous for financial names.

    Returns:
        Standard name if matched, None if unmapped.
    """
    raw_name = raw_name.strip()

    # 1. Exact match
    if raw_name in mapping:
        return mapping[raw_name]

    # 2. Contains match: mapping key is substring of raw_name
    for source, standard in mapping.items():
        if source in raw_name:
            return standard

    # 3. Reverse contains: raw_name is substring of mapping key
    for source, standard in mapping.items():
        if raw_name in source:
            return standard

    return None


def map_holdings(
    df: pd.DataFrame,
    mapping: Optional[dict[str, str]] = None,
    conn=None,
    fund_code: Optional[str] = None,
    period: Optional[str] = None,
) -> pd.DataFrame:
    """Map all industries in a holdings DataFrame.

    Args:
        df: DataFrame with 'industry' column (raw SITCA names).
        mapping: Mapping dict. If None, loads from mapping.json.
        conn: SQLite connection for logging unmapped categories.
        fund_code: Fund code for unmapped logging.
        period: Period for unmapped logging.

    Returns:
        DataFrame with 'industry' column replaced with standard names.
        Unmapped rows retain their original names.
        Adds 'mapped' boolean column.
    """
    if mapping is None:
        mapping = load_mapping()

    result = df.copy()
    mapped_names = []
    mapped_flags = []

    for raw_name in result["industry"]:
        standard = map_industry(raw_name, mapping)
        if standard is not None:
            mapped_names.append(standard)
            mapped_flags.append(True)
        else:
            mapped_names.append(raw_name)
            mapped_flags.append(False)
            logger.warning("Unmapped industry: %s", raw_name)

    result["industry"] = mapped_names
    result["mapped"] = mapped_flags

    # Log unmapped to SQLite
    unmapped_df = result[~result["mapped"]]
    if conn is not None and not unmapped_df.empty:
        from data.cache import log_unmapped_category

        for _, row in unmapped_df.iterrows():
            log_unmapped_category(
                conn,
                raw_name=row["industry"],
                fund_code=fund_code,
                period=period,
                weight=row.get("weight"),
            )

    # Check unmapped weight thresholds
    unmapped_weight = unmapped_df["weight"].sum() if "weight" in unmapped_df.columns else 0.0
    total_weight = result["weight"].sum() if "weight" in result.columns else 1.0

    if total_weight > 0:
        unmapped_ratio = unmapped_weight / total_weight
        if unmapped_ratio >= UNMAPPED_BLOCK_THRESHOLD:
            logger.error(
                "Unmapped weight %.1f%% exceeds block threshold %.1f%%",
                unmapped_ratio * 100,
                UNMAPPED_BLOCK_THRESHOLD * 100,
            )
        elif unmapped_ratio >= UNMAPPED_WARN_THRESHOLD:
            logger.warning(
                "Unmapped weight %.1f%% exceeds warn threshold %.1f%%",
                unmapped_ratio * 100,
                UNMAPPED_WARN_THRESHOLD * 100,
            )

    return result


def get_mapping_coverage(
    df: pd.DataFrame,
    mapping: Optional[dict[str, str]] = None,
) -> float:
    """Calculate mapping coverage ratio for a holdings DataFrame.

    Returns:
        Float between 0.0 and 1.0 representing the fraction of
        industries that were successfully mapped.
    """
    if mapping is None:
        mapping = load_mapping()

    total = len(df)
    if total == 0:
        return 1.0

    mapped = sum(1 for name in df["industry"] if map_industry(name, mapping) is not None)
    return mapped / total
