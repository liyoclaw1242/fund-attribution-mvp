#!/bin/bash
# TWSE index cache warmup — run daily after 14:00 market close.
# Fetches MI_INDEX data and stores in SQLite cache (24h TTL).
# Scheduled via crontab: 30 14 * * 1-5
set -euo pipefail

echo "[$(date '+%Y-%m-%d %H:%M:%S')] TWSE warmup started"

docker compose exec -T app python -c "
import sqlite3
from data.twse_client import get_industry_indices
from config.settings import DB_PATH

conn = sqlite3.connect(DB_PATH)
try:
    records = get_industry_indices(conn=conn)
    print(f'Cached {len(records)} industry indices')
finally:
    conn.close()
"

echo "[$(date '+%Y-%m-%d %H:%M:%S')] TWSE warmup complete"
