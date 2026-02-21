# Financer

Financer is a Python trading and analysis repository with three operational surfaces:

- fundamental equity analysis and report generation
- live strategy loop with risk controls and operator controls
- historical replay lab for fast strategy validation

## Start Here

Read in this order:

1. `docs/START_HERE.md`
2. `docs/ARCHITECTURE.md`
3. `docs/FEATURES_AND_FUNCTIONS.md`

## Setup

Use Python 3.12+ in a virtual environment, then install core dependencies:

```bash
python -m pip install yfinance pandas numpy plotly beautifulsoup4 lxml peewee textblob pyyaml
```

## Common Commands

Run from `Financer-/`:

```bash
# Fundamental analysis
python downloader.py "Palo Alto Networks"
python analyzer.py

# Live bot
python live_trader.py --status
python live_trader.py --loop --profile balanced

# Historical replay
python -m historical_tester
```

## Functional Areas

- `analyzer.py`, `downloader.py`, `technical.py`: filing ingestion + valuation report pipeline
- `live_trader.py`, `portfolio.py`, `indicators.py`: live strategy execution
- `historical_tester/`: historical simulation, sweeps, walk-forward, A/B compare
- `control_center/`: runtime control state + local operator API
- `core/`: reusable services (`strategy`, `risk`, `execution`, `explainability`, `alerts`)
- `configs/`: default strategy config and risk profiles
- `docs/`: operational and architecture documentation

## Operator Controls

- Start Control API:

```bash
python live_trader.py --control-api
```

- Control state file:
  - `control_center/state.json`
- Decision logs:
  - `logs/decisions/*.jsonl`
- Alert logs:
  - `logs/alerts/alerts.jsonl`
