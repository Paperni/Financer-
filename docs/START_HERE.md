# Start Here

This guide is the fastest path to run and operate the repository.

## 1) Environment

From `Financer-/`:

```bash
python -m venv .venv
.venv\Scripts\activate
python -m pip install yfinance pandas numpy plotly beautifulsoup4 lxml peewee textblob pyyaml
```

## 2) Fundamental Analysis Flow

```bash
python downloader.py "Palo Alto Networks"
python analyzer.py
```

Outputs:
- SEC artifacts under `reports/sec-edgar-filings/`
- company HTML reports under `reports/*_analysis.html`

## 3) Live Trading Flow

```bash
python live_trader.py --status
python live_trader.py --loop --profile balanced
```

Useful runtime overrides:

```bash
python live_trader.py --profile conservative --set risk.max_positions_per_sector=2 --status
```

## 4) Historical Replay Flow

```bash
python -m historical_tester
```

Modes:
- `single`
- `sweep`
- `walk`
- `compare`

## 5) Operator API

```bash
python live_trader.py --control-api
```

Primary API docs:
- `docs/API_CONTROL_CENTER.md`
