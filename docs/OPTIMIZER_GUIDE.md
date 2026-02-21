# Optimizer Guide

The historical lab includes a `freqtrade_style` optimizer interface for objective-ranked sweeps.

## Contract

- `OptimizationContext`
  - `base_kwargs`
  - `override_sets`
  - `objective_name`
  - `constraints`
  - `engine`
- `OptimizerResult`
  - `best_config`
  - `leaderboard`
  - `objective_name`
  - `trials`

## Default objective

- `return_drawdown_score = total_return_pct - abs(max_drawdown_pct)`

## Run sweep

```bash
python -m historical_tester --mode sweep --engine native
python -m historical_tester --mode sweep --engine backtrader
```

