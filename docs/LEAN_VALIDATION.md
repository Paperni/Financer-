# LEAN Validation Adapter

`historical_tester/validators/lean_adapter.py` adds a validation contract for parity checks.

## Purpose

- compare core metrics between baseline and comparison engine runs
- produce a `parity_score`
- provide a stable interface for future external LEAN execution

## Current PoC behavior

- local parity check using:
  - return gap tolerance
  - max drawdown gap tolerance
- optional in benchmark mode:

```bash
python -m historical_tester --mode benchmark --engines native,backtrader --validate-with lean
```

`lean_runner.py` is included as a future hook for external LEAN CLI/container execution.

