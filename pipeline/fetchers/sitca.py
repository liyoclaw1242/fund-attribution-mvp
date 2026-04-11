"""SITCA fetcher — monthly fund holdings from SITCA Excel files.

Reuses parsing logic from data/sitca_parser.py for Excel parsing.
Runs monthly on the 20th to pick up newly published data.
"""

import logging
from pathlib import Path

import pandas as pd

from pipeline._dates import coerce_date
from pipeline.fetchers.base import BaseFetcher

logger = logging.getLogger(__name__)

DEFAULT_SITCA_DIR = Path("data/sitca_raw")


class SitcaFetcher(BaseFetcher):
    """Parse SITCA Excel files and load fund holdings + fund info."""

    source_name = "sitca"
    default_schedule = "0 9 20 * *"
    target_table = "fund_holding"

    def __init__(self, sitca_dir: Path | str | None = None):
        self.sitca_dir = Path(sitca_dir) if sitca_dir else DEFAULT_SITCA_DIR

    async def fetch(self, params: dict) -> list[dict]:
        """Scan sitca_dir for unprocessed Excel files and parse them.

        Args:
            params: {"files": ["path1.xlsx", ...]} — optional explicit list.
        """
        explicit_files = params.get("files")
        if explicit_files:
            files = [Path(f) for f in explicit_files]
        else:
            if not self.sitca_dir.exists():
                logger.warning("SITCA data dir not found: %s", self.sitca_dir)
                return []
            files = sorted(self.sitca_dir.glob("*.xls*"))

        if not files:
            logger.info("No SITCA files to process")
            return []

        records = []
        for f in files:
            try:
                parsed = self._parse_file(f)
                records.extend(parsed)
                logger.info("Parsed %s: %d holdings", f.name, len(parsed))
            except Exception:
                logger.exception("Failed to parse %s", f.name)

        return records

    def _parse_file(self, file_path: Path) -> list[dict]:
        """Parse a single SITCA Excel file into holding records."""
        try:
            from data.sitca_parser import parse_sitca_excel
            df = parse_sitca_excel(file_path)
        except ImportError:
            logger.warning("data.sitca_parser not importable, using basic parser")
            df = pd.read_excel(file_path)

        if df.empty:
            return []

        # Extract fund code from filename (e.g., "0050_holdings.xlsx" → "0050")
        fund_code = file_path.stem.split("_")[0]

        records = []
        for _, row in df.iterrows():
            industry = str(row.get("industry", row.get("產業", "")))
            weight = row.get("weight", row.get("比重", 0))
            if isinstance(weight, str):
                weight = float(weight.replace("%", "")) / 100
            elif weight > 1:
                weight = weight / 100

            records.append({
                "fund_id": fund_code,
                "as_of_date": coerce_date(None),
                "stock_id": None,
                "stock_name": industry,
                "weight": float(weight) if pd.notna(weight) else 0,
                "asset_type": "equity",
                "sector": industry,
                "source": "sitca",
            })

        return records

    def transform(self, raw: list[dict]) -> pd.DataFrame:
        """Normalize to fund_holding schema."""
        if not raw:
            return pd.DataFrame()

        df = pd.DataFrame(raw)
        return df[["fund_id", "as_of_date", "stock_id", "stock_name",
                    "weight", "asset_type", "sector", "source"]]
