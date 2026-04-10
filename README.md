# 基金歸因分析系統 — Fund Attribution Analysis MVP

Brinson-Fachler 基金歸因分析系統，專為台灣理財顧問設計。

## Features (MVP)

- 輸入基金代碼或上傳 CSV → 解析 SITCA 持股資料
- Brinson-Fachler 歸因引擎（BF2 二因子 / BF3 三因子）
- AI 中文摘要（含數字驗證，防止幻覺）
- 瀑布圖 + 產業貢獻圖（PNG，可直接 LINE 傳送）
- 一鍵 PDF 報告（含圖表、摘要、免責聲明）

## Tech Stack

- **UI**: Streamlit
- **Engine**: Python, NumPy, Pandas
- **Charts**: Matplotlib (Noto Sans CJK)
- **PDF**: fpdf2
- **AI**: Anthropic Claude API + regex verification
- **Cache**: SQLite (WAL mode)
- **Deploy**: Docker + Nginx + systemd

## Architecture

```
db (PostgreSQL) ← pipeline (data ingestion) + service (FastAPI) ← app (Streamlit)
```

| Container | Port | Purpose |
|-----------|------|---------|
| db | 5432 | PostgreSQL data store |
| pipeline | 8080 | Scheduled data ingestion |
| service | 8000 | FastAPI REST API |
| app | 8501 | Streamlit UI |

## Quick Start

```bash
cp .env.example .env
# Edit .env with your ANTHROPIC_API_KEY

# Full stack (all 4 containers: db → pipeline + service → app)
docker-compose up

# Pipeline only
docker-compose up db pipeline

# Service API only
docker-compose up db service

# App only (original SQLite mode)
docker-compose up app

# Or local (app only)
pip install -r requirements.txt
streamlit run app.py
```

## Project Structure

```
├── app.py                  # Streamlit main app
├── interfaces.py           # Type definitions (Section 8)
├── schema.sql              # SQLite schema
├── config/settings.py      # Environment-based config
├── data/
│   ├── sitca_parser.py     # SITCA Excel parser
│   ├── twse_client.py      # TWSE API client
│   ├── industry_mapper.py  # SITCA → TSE 28 mapping
│   ├── cache.py            # SQLite CRUD + TTL
│   └── mapping.json        # Industry mapping rules
├── engine/
│   ├── brinson.py          # Brinson BF2/BF3 engine
│   └── validator.py        # Data validation
├── ai/
│   ├── prompt_builder.py   # Claude prompt construction
│   ├── claude_client.py    # API client + verification
│   ├── number_verifier.py  # Regex number check
│   └── fallback_template.py# Rule-based fallback
├── pipeline/
│   ├── Dockerfile          # Pipeline container
│   ├── requirements.txt    # Pipeline dependencies
│   ├── scheduler.py        # APScheduler orchestrator
│   ├── config.py           # Environment-based config
│   ├── db.py               # PostgreSQL pool + helpers
│   ├── schema.sql          # Pipeline DB schema
│   └── fetchers/           # Data source fetchers
├── report/
│   ├── waterfall.py        # Waterfall chart
│   ├── sector_chart.py     # Sector contribution chart
│   └── pdf_generator.py    # PDF report (fpdf2)
└── tests/
    ├── test_golden.py       # Golden dataset tests
    └── golden_data/         # Hand-calculated Excel
```

## Blueprint

Based on MVP Blueprint v1.1 — see issues for detailed specs per module.
