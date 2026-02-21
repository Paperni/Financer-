# Financer Repository

Financer contains three primary workflows:

- `fundamental analysis`: download SEC filings and generate valuation reports
- `live trading bot`: run swing-trading cycles with risk controls
- `historical tester`: replay the live bot on historical data in accelerated mode for fast validation of changes

## Quick Start

From `Financer-`:

```bash
python downloader.py "Palo Alto Networks"
python analyzer.py
python live_trader.py --status
python -m historical_tester.tester
```

## Repository Structure

- Core strategy/runtime:
  - `analyzer.py`, `downloader.py`, `technical.py`
  - `live_trader.py`, `portfolio.py`, `indicators.py`, `data_static.py`
- Historical replay:
  - `historical_tester/`
- Documentation:
  - `docs/` (`analyzer.md`, `v3_plan.md`, `ARCHITECTURE.md`)
  - `CLAUDE.md`, `README.md`
- Outputs/runtime artifacts:
  - `reports/`, `dashboard.html`, `wallet.json`, `equity_curve.json`
- Supporting folders:
  - `tests/`, `tools/`

## Historical Tester

The tester is intentionally isolated under `historical_tester/` so other developers can validate strategy changes without running live loops.

- entrypoint: `python -m historical_tester.tester`
- outputs: HTML, JSON, and CSV reports under `test_results/`
- uses separate wallet path (default `test_wallet.json`) to avoid touching live wallet files

See `historical_tester/README.md` for usage and details.

## Architecture Diagram

```mermaid
flowchart TD
    downloader[downloader.py] --> filings[reports/sec-edgar-filings]
    analyzer[analyzer.py] --> filings
    analyzer --> analysisReports[reports/*_analysis.html]
    liveTrader[live_trader.py] --> portfolio[portfolio.py]
    liveTrader --> indicators[indicators.py]
    liveTrader --> runtimeFiles[wallet.json and equity_curve.json]
    historicalTester[historical_tester/tester.py] --> liveLogic[Live Logic Replica]
    historicalTester --> historicalReports[test_results/*]
```

## Cleanup Notes (Completed)

- Historical testing code has been consolidated under `historical_tester/`
- Documentation files were moved into `docs/`
- Validation and helper scripts were grouped under `tests/` and `tools/`
