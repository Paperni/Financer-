# Historical Tester

Historical replay environment for the live trading bot.

## Goal

Run large historical windows as accelerated "live-like" cycles so developers can evaluate behavior, regressions, and performance quickly.

## Run

From `Financer-`:

```bash
python -m historical_tester --mode interactive
```

or:

```bash
python -m historical_tester --mode single --engine native
python -m historical_tester --mode single --engine backtrader
python -m historical_tester --mode benchmark --engines native,backtrader
python -m historical_tester --mode benchmark --engines native,backtrader --validate-with lean
python -m historical_tester --mode sweep --engine native
```

Interactive flow now supports:

- config path (default `configs/strategy/default.yaml`)
- profile selection (`conservative`, `balanced`, `aggressive`)
- optional overrides through code-level constructor args

Modes:

- `single` (default)
- `benchmark` (standardized side-by-side report)
- `sweep` (objective-ranked parameter sweep presets)
- `interactive` (prompt-driven execution)

Engine adapters:

- `native` (internal replay baseline)
- `backtrader` (PoC adapter)

## What It Does

- replays market hours through historical windows
- uses live strategy flow (position updates, exits, scan-and-buy, pyramiding)
- collects performance metrics (returns, drawdown, win rate, distribution, etc.)
- exports reports (HTML/JSON/CSV)

## Main Files

- `tester.py`: orchestration and interactive CLI
- `cli.py`: non-interactive CLI entrypoint
- `orchestrator.py`: engine routing + benchmark suite execution
- `time_simulator.py`: simulated clock and market-hours behavior
- `historical_cache.py`: time-bounded historical cache
- `metrics.py`: performance/statistics collector
- `report_generator.py`: output generators
- `engines/`: engine contracts + adapters
- `benchmark/`: standardized benchmark schema/report writer
- `optimizers/`: optimizer contracts + implementations
- `validators/`: validation contracts + LEAN parity adapter

## Safety

- default wallet path is test-specific to avoid changing the live wallet
- report outputs are isolated in `test_results/`

## Quick Smoke Test

```bash
python -m compileall historical_tester
python -m historical_tester --help
```
