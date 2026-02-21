# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Financer is a Python CLI investment analysis platform. It downloads SEC EDGAR filings, fetches live market data from Yahoo Finance, runs a 6-phase fundamental analysis framework, performs multi-method valuation (DCF, Relative, EPV, Analyst), generates interactive technical charts, and outputs self-contained HTML reports with actionable investment strategies.

## Setup

Python 3.12 with a local venv.

```bash
# Activate venv
source .venv/Scripts/activate   # Windows Git Bash
# or: .venv\Scripts\activate    # Windows CMD

# Key packages
python -m pip install yfinance sec-edgar-downloader beautifulsoup4 pandas lxml peewee textblob plotly numpy
```

## Running

```bash
# Step 1: Download filings for a company
python downloader.py "Palo Alto Networks"

# Step 2: Analyze all downloaded tickers (auto-detects from reports/ directory)
python analyzer.py

# View reports
start reports\AAPL_analysis.html   # Windows

# Historical accelerated replay tester (live-like simulation)
python -m historical_tester.tester
```

## Architecture

Two-stage pipeline: download then analyze.

### Core Files

1. **downloader.py** — Converts company name to ticker via `yfinance.Search()`, downloads 1 latest 10-K and 2 latest 10-Q filings from SEC EDGAR.

2. **analyzer.py** (~1500+ lines) — The main analysis engine. Orchestrates everything:
   - Fetches live market data from yfinance (info, financials, balance_sheet, cashflow, growth_estimates, history)
   - Parses SEC 10-K filings for raw metrics and NLP text analysis
   - Runs 6-phase investment analysis framework (see `docs/analyzer.md` for spec)
   - Performs multi-method valuation with composite blending
   - Compares against sector peers
   - Generates self-contained HTML reports with embedded Plotly charts

3. **technical.py** — Generates interactive Plotly charts (candlesticks, SMA 50/200, Bollinger Bands, RSI, MACD, volume). Called by analyzer.py.

### Supporting Files (standalone, not imported by analyzer.py)

- **qualitative.py** — `QualitativeIntelligence` class (NLP moat/sentiment). Logic inlined into analyzer.py.
- **metrics.py** — `QuantitativeCore` class (ROIC, FCF, DCF). Logic inlined into analyzer.py.
- **data_engine.py** — `DataEngine` wrapper class. Not used; analyzer.py handles data fetching directly.
- **tools/debug_nlp.py** — TextBlob test script.
- **historical_tester/** — accelerated historical replay environment for the live trading bot (time simulator, historical cache, metrics, reports).

### Analysis Pipeline (analyzer.py)

```
fetch_yfinance_data() → parse 10-K text →
  Phase 1: Circle of Competence (NLP simplicity + predictability)
  Phase 2: Moat Analysis (margins + NLP keyword scan with strength)
  Phase 3: Quantitative Vitals (ROIC, FCF yield, Debt/EBITDA, margins)
  Phase 4: Management & Capital Allocation (insider ownership, buybacks, sentiment)
  → Fetch sector peers → Phase 6: Sector Comparison (rankings, medians)
  Phase 5: Multi-Method Valuation (DCF + Relative + EPV + Analyst blend)
  → compute_strategy() (9-label strategy matrix)
  → generate_html_report() with Plotly technical chart
```

### Valuation Engine

- **DCF**: Two-stage model, normalized FCF, analyst growth from `stockTrend` column, CAPM/beta discount rate
- **Relative**: Peer median P/E applied to target EPS (trailing + forward)
- **EPV**: Earnings Power Value (no-growth floor) = NOPAT / cost of equity
- **Analyst**: Consensus price target from yfinance
- **Composite**: Weighted blend (DCF 40%, Relative 25%, Analyst 20%, EPV 15%)

### Strategy Matrix

9 labels based on fundamentals % (phases 1-4) vs valuation % (phase 5):
STRONG BUY, QUALITY HOLD, WATCHLIST - OVERVALUED, VALUE OPPORTUNITY, HOLD - MIXED, WATCHLIST - WEAK VALUE, SPECULATIVE VALUE, AVOID - WEAK, AVOID

### Data Storage Layout

```
reports/
  sec-edgar-filings/{TICKER}/{FILING_TYPE}/{ACCESSION_NUMBER}/
      primary-document.html   ← parsed by analyzer
      full-submission.txt
  {TICKER}_analysis.html      ← generated report
```

### Key Constants

- `SECTOR_DISCOUNT_RATES`: Per-sector discount rates (fallback when beta unavailable)
- `SECTOR_PEER_CANDIDATES`: Hardcoded 11 GICS sectors with 10-16 tickers each
- `MARGIN_OF_SAFETY_TARGET`: 0.30 (30% margin of safety for "buy" signal)
- `TERMINAL_GROWTH`: 0.025 (2.5%)
- `RISK_FREE_RATE`: 0.043 (10-year Treasury)

### Notes

- The downloader uses a placeholder email for SEC EDGAR API access (required by SEC)
- yfinance `growth_estimates` returns column `stockTrend` (not `Stock`) — this was a past bug
- Moat scores from NLP can push phase2 score above max_score; it's clamped via `min(score, max_score)`
- Windows console: avoid Unicode box-drawing chars (cp1252 encoding issue)
- No tests or CI exist currently
