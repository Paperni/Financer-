# Standardized Benchmark Report

Benchmark mode executes multiple engines on the same test window and writes a normalized report.

## Outputs

- `test_results/benchmarks/benchmark_*.json`
- `test_results/benchmarks/benchmark_*.csv`
- `test_results/benchmarks/benchmark_*.html`

## Canonical record fields

- `engine`
- `total_return_pct`
- `win_rate_pct`
- `max_drawdown_pct`
- `sharpe_ratio`
- `total_trades`
- `fee_drag_pct`
- `avg_hold_time_hours`

## Run benchmark

```bash
python -m historical_tester --mode benchmark --engines native,backtrader
python -m historical_tester --mode benchmark --engines native,backtrader --validate-with lean
```

