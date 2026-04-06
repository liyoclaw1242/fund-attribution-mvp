"""Parse SITCA FHS/FHW Excel files into fund holdings DataFrame.

Supports two formats:
1. SITCA FHS format: rows with industry, market_value, weight columns
2. Golden dataset format: "holdings" sheet with industry, Wp, Wb, Rp, Rb

Primary path: pandas.read_excel on manually-downloaded Excel files.
No web scraping in MVP.
"""

from pathlib import Path
from typing import Optional

import pandas as pd

# Expected column names in SITCA FHS Excel (Chinese headers)
SITCA_INDUSTRY_COLS = ["產業", "產業類別", "行業", "類股", "industry"]
SITCA_WEIGHT_COLS = ["比重", "權重", "比例", "占比", "weight", "Wp"]
SITCA_RETURN_COLS = ["報酬率", "��酬", "return_rate", "Rp"]
SITCA_VALUE_COLS = ["市值", "淨值", "金額", "market_value"]


def _find_column(df: pd.DataFrame, candidates: list[str]) -> Optional[str]:
    """Find the first matching column name from candidates."""
    for col in candidates:
        if col in df.columns:
            return col
    return None


def parse_sitca_excel(
    file_path: str | Path,
    fund_code: Optional[str] = None,
    sheet_name: str | int = 0,
) -> pd.DataFrame:
    """Parse a SITCA FHS/FHW Excel file into a standardized DataFrame.

    Args:
        file_path: Path to the Excel file.
        fund_code: Optional fund code (extracted from filename if not provided).
        sheet_name: Sheet name or index to read. Defaults to first sheet.

    Returns:
        pd.DataFrame with columns: [industry, weight, return_rate]
        weight is a float between 0 and 1 (proportion, not percentage).
        return_rate may be NaN if not available in the source file.

    Raises:
        ValueError: If the file is empty or required columns are missing.
        FileNotFoundError: If the file does not exist.
    """
    file_path = Path(file_path)
    if not file_path.exists():
        raise FileNotFoundError(f"SITCA file not found: {file_path}")

    # Try reading the specified sheet
    try:
        df = pd.read_excel(file_path, sheet_name=sheet_name)
    except Exception as e:
        raise ValueError(f"Failed to read Excel file {file_path}: {e}") from e

    if df.empty:
        raise ValueError(f"Empty Excel file: {file_path}")

    # Detect format: golden dataset vs SITCA FHS
    if "Wp" in df.columns and "Rp" in df.columns:
        return _parse_golden_format(df)

    return _parse_sitca_format(df)


def _parse_golden_format(df: pd.DataFrame) -> pd.DataFrame:
    """Parse the golden dataset holdings format (industry, Wp, Wb, Rp, Rb)."""
    result = pd.DataFrame({
        "industry": df["industry"],
        "weight": df["Wp"].astype(float),
        "return_rate": df["Rp"].astype(float),
    })
    return _validate_output(result)


def _parse_sitca_format(df: pd.DataFrame) -> pd.DataFrame:
    """Parse SITCA FHS Excel format with Chinese column headers."""
    # Find industry column
    industry_col = _find_column(df, SITCA_INDUSTRY_COLS)
    if industry_col is None:
        raise ValueError(
            f"Cannot find industry column. Available: {df.columns.tolist()}. "
            f"Expected one of: {SITCA_INDUSTRY_COLS}"
        )

    # Find weight column
    weight_col = _find_column(df, SITCA_WEIGHT_COLS)
    value_col = _find_column(df, SITCA_VALUE_COLS)

    if weight_col is None and value_col is None:
        raise ValueError(
            f"Cannot find weight or market_value column. Available: {df.columns.tolist()}. "
            f"Expected one of: {SITCA_WEIGHT_COLS} or {SITCA_VALUE_COLS}"
        )

    # Find return column (optional)
    return_col = _find_column(df, SITCA_RETURN_COLS)

    # Build industry series
    industry = df[industry_col].astype(str).str.strip()

    # Build weight series
    if weight_col is not None:
        weight = pd.to_numeric(df[weight_col], errors="coerce")
        # If weights look like percentages (> 1), convert to proportions
        if weight.max() > 1.0:
            weight = weight / 100.0
    else:
        # Compute weight from market value
        values = pd.to_numeric(df[value_col], errors="coerce")
        total = values.sum()
        if total == 0:
            raise ValueError("Total market value is zero — cannot compute weights")
        weight = values / total

    # Build return_rate series
    if return_col is not None:
        return_rate = pd.to_numeric(df[return_col], errors="coerce")
        # If returns look like percentages (abs > 1), convert to decimals
        if return_rate.abs().max() > 1.0:
            return_rate = return_rate / 100.0
    else:
        return_rate = pd.Series([float("nan")] * len(df))

    result = pd.DataFrame({
        "industry": industry,
        "weight": weight,
        "return_rate": return_rate,
    })

    # Drop rows with missing industry or zero weight
    result = result.dropna(subset=["industry", "weight"])
    result = result[result["weight"] > 0].reset_index(drop=True)

    return _validate_output(result)


def _validate_output(df: pd.DataFrame) -> pd.DataFrame:
    """Validate the output DataFrame."""
    if df.empty:
        raise ValueError("Parsed DataFrame is empty after filtering")

    required = ["industry", "weight", "return_rate"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"Missing required columns: {missing}")

    # Ensure types
    df["weight"] = df["weight"].astype(float)
    df["return_rate"] = pd.to_numeric(df["return_rate"], errors="coerce")

    return df


def parse_and_cache(
    file_path: str | Path,
    fund_code: str,
    period: str,
    conn=None,
    ttl_hours: int = 720,  # 30 days
    sheet_name: str | int = 0,
) -> pd.DataFrame:
    """Parse SITCA file and store in SQLite cache.

    Args:
        file_path: Path to the SITCA Excel file.
        fund_code: Fund code (e.g., "0050").
        period: Period string (e.g., "2026-03").
        conn: SQLite connection. If None, caching is skipped.
        ttl_hours: Cache TTL in hours. Default 30 days (720h).
        sheet_name: Sheet name or index.

    Returns:
        Parsed DataFrame.
    """
    df = parse_sitca_excel(file_path, fund_code=fund_code, sheet_name=sheet_name)

    if conn is not None:
        from data.cache import upsert_fund_holdings

        holdings = df.to_dict("records")
        upsert_fund_holdings(conn, fund_code, period, holdings, ttl_hours=ttl_hours)

    return df
