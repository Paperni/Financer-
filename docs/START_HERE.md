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
python -m historical_tester --mode single --engine native
python -m historical_tester --mode single --engine backtrader
python -m historical_tester --mode benchmark --engines native,backtrader
python -m historical_tester --mode benchmark --engines native,backtrader --validate-with lean
```

Modes:
- `single`
- `benchmark`
- `sweep`
- `interactive`

Engine options:
- `native`: canonical internal replay engine
- `backtrader`: adapter PoC with parity-mode execution path

## 5) Smoke Test

```bash
python -m compileall historical_tester tests
python -m historical_tester --help
```

Optional:

```bash
python -m pip install pytest
python -m pytest -q tests/test_engine_contract.py tests/test_backtrader_engine_smoke.py tests/test_optimizer_contract.py tests/test_lean_adapter_contract.py
```

## 6) Operator API

```bash
python live_trader.py --control-api
```

Primary API docs:
- `docs/API_CONTROL_CENTER.md`
