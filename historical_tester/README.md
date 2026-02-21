# Historical Tester

Historical replay environment for the live trading bot.

## Goal

Run large historical windows as accelerated "live-like" cycles so developers can evaluate behavior, regressions, and performance quickly.

## Run

From `Financer-`:

```bash
python -m historical_tester.tester
```

or:

```bash
python -m historical_tester
```

## What It Does

- replays market hours through historical windows
- uses live strategy flow (position updates, exits, scan-and-buy, pyramiding)
- collects performance metrics (returns, drawdown, win rate, distribution, etc.)
- exports reports (HTML/JSON/CSV)

## Main Files

- `tester.py`: orchestration and interactive CLI
- `time_simulator.py`: simulated clock and market-hours behavior
- `historical_cache.py`: time-bounded historical cache
- `metrics.py`: performance/statistics collector
- `report_generator.py`: output generators

## Safety

- default wallet path is test-specific to avoid changing the live wallet
- report outputs are isolated in `test_results/`
