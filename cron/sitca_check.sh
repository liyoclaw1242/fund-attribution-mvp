#!/bin/bash
# SITCA monthly data freshness check + unmapped industry alert.
# Scheduled via crontab: 0 9 20 * *
set -euo pipefail

echo "[$(date '+%Y-%m-%d %H:%M:%S')] SITCA check started"

# 1. Check data freshness: are there files from this month?
CURRENT_MONTH=$(date '+%Y%m')
SITCA_DIR="data/sitca_raw"

RECENT_FILES=$(find "$SITCA_DIR" -name "*.xls*" -newermt "$(date '+%Y-%m-01')" 2>/dev/null | wc -l | tr -d ' ')

if [ "$RECENT_FILES" -eq 0 ]; then
    echo "WARNING: No SITCA files updated this month ($CURRENT_MONTH)."
    echo "Action required: Follow ops/sitca_refresh_guide.md to download latest data."
else
    echo "OK: $RECENT_FILES SITCA file(s) updated this month."
fi

# 2. Check for unmapped industries in the database
docker compose exec -T app python -c "
import sqlite3
from config.settings import DB_PATH

conn = sqlite3.connect(DB_PATH)
try:
    cursor = conn.execute('''
        SELECT raw_name, fund_code, weight
        FROM unmapped_categories
        WHERE created_at > datetime(\"now\", \"-30 days\")
        ORDER BY weight DESC
    ''')
    rows = cursor.fetchall()
    if rows:
        print(f'ALERT: {len(rows)} unmapped industry categories in last 30 days:')
        for raw_name, fund_code, weight in rows:
            w = f'{weight*100:.1f}%' if weight else 'N/A'
            print(f'  - {raw_name} (fund: {fund_code}, weight: {w})')
        print('Action required: Update data/mapping.json')
    else:
        print('OK: No unmapped industries in last 30 days.')
finally:
    conn.close()
"

echo "[$(date '+%Y-%m-%d %H:%M:%S')] SITCA check complete"
