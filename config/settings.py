"""Application settings — loaded from environment variables."""

import os

BRINSON_MODE = os.getenv("BRINSON_MODE", "BF2")  # BF2 or BF3
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
AI_TIMEOUT_SECONDS = 10
TWSE_RATE_LIMIT_DELAY = float(os.getenv("TWSE_RATE_LIMIT_DELAY", "2.0"))
SITCA_DATA_DIR = os.getenv("SITCA_DATA_DIR", "data/sitca_raw")
DB_PATH = os.getenv("DB_PATH", "cache.db")

# Unmapped industry thresholds
UNMAPPED_WARN_THRESHOLD = 0.03   # 3%
UNMAPPED_BLOCK_THRESHOLD = 0.10  # 10%

# Chart settings
CHART_DPI = 180
COLORS = {
    "benchmark": "#888780",
    "allocation": "#378ADD",
    "selection": "#1D9E75",
    "interaction": "#BA7517",
    "fund_total": "#534AB7",
    "positive": "#1D9E75",
    "negative": "#E24B4A",
}

# Anomaly detection thresholds (overridable via env)
ANOMALY_PE_PERCENTILE = float(os.getenv("ANOMALY_PE_PERCENTILE", "90"))
ANOMALY_RSI_OVERBOUGHT = float(os.getenv("ANOMALY_RSI_OVERBOUGHT", "70"))
ANOMALY_OUTFLOW_DAYS = int(os.getenv("ANOMALY_OUTFLOW_DAYS", "5"))
ANOMALY_FOREIGN_SELL_DAYS = int(os.getenv("ANOMALY_FOREIGN_SELL_DAYS", "5"))
ANOMALY_CONCENTRATION = float(os.getenv("ANOMALY_CONCENTRATION", "0.40"))
ANOMALY_STYLE_DRIFT = float(os.getenv("ANOMALY_STYLE_DRIFT", "0.15"))
