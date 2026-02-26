# Engine Interface Contract

The historical lab now supports pluggable backtest engines under `historical_tester/engines/`.

## Contract

- `EngineContext`
  - `tester_kwargs: dict[str, Any]`
  - `run_label: str | None`
  - `run_dir: Path | None`
  - `extra: dict[str, Any]`
- `EngineResult`
  - `run_id: str`
  - `engine: str`
  - `config_hash: str`
  - `metrics: dict`
  - `trades: list[dict]`
  - `equity_curve: list`
  - `metadata: dict`

## Implementations

- `native_engine.py`: canonical replay of current live-logic stack.
- `backtrader_engine.py`: PoC adapter with parity mode and metadata for Backtrader capability.

## Usage

```bash
python -m historical_tester --mode single --engine native
python -m historical_tester --mode single --engine backtrader
```

