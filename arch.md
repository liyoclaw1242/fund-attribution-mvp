# Architecture — Fund Attribution Analysis MVP

## Domain Model

### Core Domains
- **Fund Data Pipeline**: Ingests fund holding data from SITCA Excel or CSV uploads, maps industries to TSE 28 standard, caches in SQLite. Key entities: FundHoldings (DataFrame), BenchmarkData (dict), IndustryMap.
- **Attribution Engine**: Brinson-Fachler attribution (BF2 two-factor, BF3 three-factor). Takes fund + benchmark data, produces AttributionResult with allocation/selection/interaction effects per industry.
- **AI Summary**: Constructs prompts from attribution results, calls Claude API, verifies numbers via regex, falls back to rule-based template on mismatch. Produces LINE message, PDF summary, and advisor note in Traditional Chinese.
- **Report Generation**: Waterfall chart + sector contribution chart (Matplotlib, CJK fonts), 2-page PDF (fpdf2) with KPIs, narrative, charts, detail table, disclaimer.
- **Presentation**: Streamlit UI for input (fund code or CSV upload), benchmark selection, BF mode toggle, result display (KPI cards, charts, AI tabs), and export (PNG/PDF).

### Bounded Contexts
```mermaid
graph LR
  UI[Streamlit UI] --> |fund code / CSV| DataPipeline[Data Pipeline]
  DataPipeline --> |FundHoldings + BenchmarkData| Engine[Attribution Engine]
  Engine --> |AttributionResult| AI[AI Summary]
  Engine --> |AttributionResult| Charts[Report: Charts]
  AI --> |AISummary| PDF[Report: PDF]
  Charts --> |PNG bytes| PDF
  Charts --> |PNG bytes| UI
  AI --> |AISummary| UI
  PDF --> |PDF bytes| UI
  DataPipeline --> |cache| SQLite[(SQLite WAL)]
```

### Aggregate Roots
| Aggregate | Key Entities | Invariants |
|-----------|-------------|------------|
| FundHoldings | industry, weight, return_rate | Weights sum to 1.0 (±0.02), single industry ≤ 60% |
| BenchmarkData | industry → {weight, return, index_name} | Weights sum to 1.0 (exact) |
| AttributionResult | allocation/selection/interaction per industry | alloc + select (+ interaction) = excess_return (< 1e-10) |
| AISummary | line_message, pdf_summary, advisor_note | All numbers in output must match source (0.01% tolerance) |

## System Architecture

### Tech Stack
| Layer | Technology | Version |
|-------|-----------|---------|
| Frontend | Streamlit | ≥1.30 |
| Engine | Python / NumPy / Pandas | 3.11 / ≥1.25 / ≥2.1 |
| Charts | Matplotlib + Noto Sans CJK | ≥3.8 |
| PDF | fpdf2 | ≥2.7 |
| AI | Anthropic Claude API | ≥0.40 |
| Cache/DB | SQLite (WAL mode) | built-in |
| External Data | TWSE OpenAPI (TWT49U, MI_INDEX) | REST/JSON |
| External Data | SITCA FHS/FHW Excel files | Manual upload |
| Deploy | Docker + Nginx + systemd | Python 3.11-slim |

### Data Flow
```mermaid
sequenceDiagram
  participant U as Advisor (Streamlit)
  participant D as Data Pipeline
  participant DB as SQLite Cache
  participant E as Brinson Engine
  participant V as Validator
  participant AI as Claude API
  participant R as Report Generator

  U->>D: Fund code or CSV upload
  D->>DB: Check cache (TTL)
  alt Cache miss
    D->>D: Parse SITCA Excel / fetch TWSE API
    D->>D: Map industries (SITCA → TSE 28)
    D->>DB: Store with TTL
  end
  DB-->>D: FundHoldings + BenchmarkData
  D->>E: Holdings + Benchmark
  E->>V: Validate inputs
  V-->>E: Pass / Warn / Block
  E->>E: Compute BF2 or BF3
  E->>V: Validate outputs (Brinson assertion)
  E-->>U: AttributionResult (KPI cards)
  E->>AI: AttributionResult → prompt
  AI->>AI: Number verification (regex)
  alt Verification pass
    AI-->>U: AISummary
  else Verification fail
    AI->>AI: Rule-based fallback
    AI-->>U: AISummary (fallback_used=true)
  end
  E->>R: AttributionResult → charts (PNG)
  R-->>U: Waterfall + Sector charts
  U->>R: Export request
  R->>R: Generate 2-page PDF
  R-->>U: PDF download
```

### Folder Structure
```
├── app.py                  # Streamlit entry point
├── interfaces.py           # Type contracts (Section 8)
├── schema.sql              # SQLite DDL
├── config/settings.py      # Env-based configuration
├── data/
│   ├── sitca_parser.py     # SITCA Excel → DataFrame
│   ├── twse_client.py      # TWSE REST API + rate limiting
│   ├── industry_mapper.py  # SITCA → TSE 28 mapping
│   ├── cache.py            # SQLite CRUD + TTL
│   └── mapping.json        # 30 industry mapping rules
├── engine/
│   ├── brinson.py          # BF2/BF3 attribution math
│   └── validator.py        # Input/output validation
├── ai/
│   ├── prompt_builder.py   # Attribution → Claude prompt
│   ├── claude_client.py    # API call + pipeline
│   ├── number_verifier.py  # Regex % matching
│   └── fallback_template.py# Rule-based Chinese text
├── report/
│   ├── waterfall.py        # Waterfall chart (Matplotlib)
│   ├── sector_chart.py     # Horizontal bar chart
│   └── pdf_generator.py    # 2-page A4 PDF (fpdf2)
└── tests/
    ├── test_golden.py      # Golden dataset verification
    └── golden_data/        # Hand-calculated Excel files
```

## API Contracts

### Internal Module Interfaces (interfaces.py)

| Interface | Input | Output |
|-----------|-------|--------|
| sitca_parser.parse() | Excel file path | `pd.DataFrame[industry, weight, return_rate]` |
| twse_client.fetch_benchmark() | index name, period | `BenchmarkData` (dict[str, dict]) |
| industry_mapper.map() | raw SITCA DataFrame | Mapped DataFrame (TSE 28 standard) |
| cache.get/set() | fund_code, period | Cached data with TTL |
| brinson.compute() | FundHoldings, BenchmarkData, mode | `AttributionResult` |
| validator.validate_input/output() | Holdings / Result | Pass / Warn / Block |
| prompt_builder.build() | AttributionResult | Prompt string |
| claude_client.summarize() | AttributionResult | `AISummary` |
| number_verifier.verify() | AI text, source numbers | bool |
| waterfall.render() | AttributionResult | PNG bytes |
| sector_chart.render() | AttributionResult | PNG bytes |
| pdf_generator.generate() | AttributionResult, AISummary, charts | PDF bytes |

### External APIs

| Method | Endpoint | Purpose | Rate Limit |
|--------|----------|---------|------------|
| GET | `openapi.twse.com.tw/v1/exchangeReport/TWT49U` | Weighted return index | 2s delay |
| GET | `openapi.twse.com.tw/v1/exchangeReport/MI_INDEX` | Industry index returns | 2s delay |

## User Journey Map

### Primary Flow
1. **Input**: Advisor enters fund code OR uploads CSV → selects benchmark → picks BF2/BF3 → clicks "開始分析"
2. **Processing**: Data pipeline fetches/parses → engine computes attribution → AI generates summary → charts rendered
3. **Results**: KPI cards (5 metrics) → Waterfall chart → Sector chart → AI tabs (LINE/PDF/Advisor note)
4. **Export**: Download PNG (waterfall) → Download PDF (full 2-page report with advisor name)

### Key Decision Points
| Step | User Decision | System Response |
|------|--------------|-----------------|
| Input method | Fund code vs CSV upload | SITCA parser vs direct DataFrame |
| Benchmark | Choose index (加權/電子/金融) | Fetch corresponding TWSE data |
| BF mode | BF2 (simpler) vs BF3 (detailed) | Include/exclude interaction effect |
| Export | PNG (quick share via LINE) vs PDF (formal report) | Different output pipelines |

## Product Roadmap Context

### Current Phase
**MVP** — Sprint 0 in progress (golden dataset + dev environment)

### Sprint Plan
| Sprint | Focus | Issues |
|--------|-------|--------|
| 0 | Golden dataset + dev environment | #1, #2 |
| 1 | Data pipeline (SITCA, TWSE, cache, mapper) | #3, #4, #5, #6, #16 |
| 2 | Attribution engine + basic UI | #7, #8, #9 |
| 3 | AI summary + charts + PDF | #10, #11, #12, #13 |
| 4 | Deploy + QA | #14, #15 |

### Recent Decisions
- 2026-04-06: All 16 issues pre-decomposed from Blueprint v1.1, dependency chain established
- BF2 as default mode, BF3 opt-in (simpler first experience for advisors)
- SITCA data via manual Excel upload (no web scraping in MVP)
- Number verification (regex) as AI hallucination guard — fallback to rule-based template

### Known Tech Debt
| Item | Impact | Priority |
|------|--------|----------|
| No golden dataset yet | Cannot validate engine correctness | Critical (Sprint 0) |
| All modules are stubs | No functionality | Critical (being addressed) |
| No automated tests beyond golden | Regression risk | Medium |
| Hardcoded benchmark options (3) | Limited coverage | Low |
| No auth / multi-user | Single advisor assumed | Low (post-MVP) |

### Planned Features (post-MVP)
| Feature | Domain Impact | Dependencies |
|---------|--------------|-------------|
| SITCA auto-fetch (monthly SOP) | New cron job, data pipeline extension | Issue #16 |
| Multi-period comparison | Engine needs time-series support | Engine refactor |
| Custom benchmark composition | New UI for benchmark building | DB schema change |

## Failure Modes

| Service Boundary | Failure | Detection | Recovery | User Impact |
|-----------------|---------|-----------|----------|-------------|
| TWSE API | Rate limited / down | HTTP 429/5xx | 24h SQLite cache + fallback CSV | Stale data (acceptable for monthly analysis) |
| SITCA Excel | Corrupted / wrong format | Parser validation | Error message to user | Must re-upload |
| Industry Mapping | Unmapped categories | unmapped_weight check | ≥10% → block analysis, <10% → warn | Partial attribution (with warning) |
| Brinson Assertion | Effects don't sum to excess | Tolerance check (1e-10) | Block result, show error | No output (data integrity protected) |
| Claude API | Timeout / error | 10s timeout | Rule-based fallback template | Slightly less natural summary |
| AI Hallucination | Numbers in summary ≠ source | Regex number verification | Auto-switch to fallback | Correct numbers guaranteed |
| SQLite | DB locked / corrupted | WAL mode + busy_timeout | 5s retry, then fail gracefully | Temporary service interruption |
| PDF/Chart | CJK font missing | Font path check | Docker image includes fonts-noto-cjk | Broken characters (deploy issue) |
