import argparse
import logging
import time
from pathlib import Path

from financer.cli.run_replay import run_replay

logging.basicConfig(level=logging.INFO)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", default="2021-01-01")
    parser.add_argument("--end", default="2025-12-31")
    args = parser.parse_args()

    # The benchmark parameters (Config C from prior prompts)
    params = {
        "min_entry_score": 5.0, 
        "stop_loss_atr_mult": 1.5, 
        "cautious_size_mult": 0.5
    }

    # Load 260 tickers from legacy data
    from legacy.data_static import BROAD_STOCKS, BROAD_ETFS
    tickers = list(dict.fromkeys(BROAD_STOCKS + BROAD_ETFS))

    # The benchmark parameters (Config C from prior prompts)
    params = {
        "min_entry_score": 5.0, 
        "stop_loss_atr_mult": 1.5, 
        "cautious_size_mult": 0.5
    }

    print(f"Running Phase 2 Validation for {args.start} to {args.end}")
    
    # 1. Run Baseline (No Intelligence)
    print("\n[1/2] Running Baseline (Intelligence Disabled)...")
    baseline_dir = Path(f"artifacts/phase2_baseline_{int(time.time())}")
    baseline_dir.mkdir(parents=True, exist_ok=True)
    _, curve_base, trades_base, _ = run_replay(
        tickers=tickers,
        start=args.start,
        end=args.end,
        intelligence_enabled=False,
        **params
    )
    
    import json
    with open(baseline_dir / "equity_curve.json", "w") as f:
        json.dump(curve_base, f, indent=2)
    with open(baseline_dir / "trade_log.json", "w") as f:
        json.dump(trades_base, f, indent=2)
    with open(baseline_dir / "config.json", "w") as f:
        json.dump(params, f, indent=2)
        
    # 2. Run MIE Enabled (Phase 2 Intelligence)
    print("\n[2/2] Running MIE Enabled (Phase 2 Intelligence)...")
    mie_dir = Path(f"artifacts/phase2_mie_{int(time.time())}")
    mie_dir.mkdir(parents=True, exist_ok=True)
    _, curve_mie, trades_mie, _ = run_replay(
        tickers=tickers,
        start=args.start,
        end=args.end,
        intelligence_enabled=True,
        **params
    )

    with open(mie_dir / "equity_curve.json", "w") as f:
        json.dump(curve_mie, f, indent=2)
    with open(mie_dir / "trade_log.json", "w") as f:
        json.dump(trades_mie, f, indent=2)
    with open(mie_dir / "config.json", "w") as f:
        json.dump(params, f, indent=2)

    print("\n--- DONE ---")
    print(f"Run report_years.py on the two output directories:")
    print(f"  python -m financer.cli.report_years --run {baseline_dir}")
    print(f"  python -m financer.cli.report_years --run {mie_dir}")

if __name__ == "__main__":
    main()
