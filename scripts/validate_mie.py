"""Quick validation: Config C baseline vs MIE-enabled.

Runs replay with Config C params + intelligence_enabled=True,
saves artifacts, and runs report_years for comparison.
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from financer.execution import policy
from financer.models import sizing
from financer.engines.swing import scorecard
from financer.cli.run_replay import run_replay, save_artifacts
from financer.features.build import build_features
from legacy.data_static import BROAD_STOCKS, BROAD_ETFS
from financer.data.prices import get_bars, DataFetchError
import pandas as pd
import time

# Config C params
CONFIG_C = {
    "score_threshold": 5,
    "stop_atr_mult": 1.75,
    "time_stop_bars": 50,
    "rsi_band": [35, 50],
    "cautious_size_mult": 0.75,
    "max_positions": 10,
    "risk_per_trade_pct": 0.01,
    "max_heat_R": 5.0,
    "pyramiding_mode": "off",
}

START = "2021-01-01"
END = "2025-12-31"

def main():
    # Patch globals
    policy.STOP_LOSS_ATR_MULTIPLIER = CONFIG_C["stop_atr_mult"]
    sizing.ATR_STOP_MULTIPLIER = CONFIG_C["stop_atr_mult"]
    policy.TIME_STOP_DAYS = CONFIG_C["time_stop_bars"]
    scorecard.RSI_BAND_LOWER = CONFIG_C["rsi_band"][0]
    scorecard.RSI_BAND_UPPER = CONFIG_C["rsi_band"][1]
    sizing.CAUTIOUS_SIZE_MULT = CONFIG_C["cautious_size_mult"]

    # Build universe
    universe = list(set(BROAD_STOCKS + BROAD_ETFS))
    if "SPY" not in universe:
        universe.append("SPY")

    print(f"Universe: {len(universe)} tickers")
    print("Precomputing features...")

    t0 = time.time()
    feature_dfs = {}
    skipped = []
    for ticker in universe:
        try:
            df = build_features(ticker, start=START, end=END)
            if not df.empty:
                feature_dfs[ticker] = df
        except Exception as e:
            skipped.append(ticker)

    print(f"Features built for {len(feature_dfs)} tickers in {time.time()-t0:.1f}s (skipped {len(skipped)})")

    # Transpose once
    print("Transposing features...")
    daily_features = {}
    for ticker, df in feature_dfs.items():
        ticker_dict = df.to_dict('index')
        for d, row_dict in ticker_dict.items():
            if pd.isna(d):
                continue
            ts = pd.to_datetime(d).normalize()
            if ts not in daily_features:
                daily_features[ts] = {}
            daily_features[ts][ticker] = row_dict

    # Debug: verify SPY is available and regime works
    print(f"\nSPY in feature_dfs: {'SPY' in feature_dfs}")
    if "SPY" in feature_dfs:
        spy = feature_dfs["SPY"]
        print(f"SPY shape: {spy.shape}, index type: {type(spy.index)}")
        from financer.intelligence.config import load_config as _lc
        from financer.intelligence.regime import classify_regime_at_date as _cr
        _cfg = _lc()
        # Test mid-2022 bear
        _p = _cr(spy, pd.Timestamp("2022-06-15"), _cfg)
        print(f"Regime 2022-06-15: max_pos={_p.max_positions}, mult={_p.position_size_multiplier}")
        # Test mid-2021 bull
        _p2 = _cr(spy, pd.Timestamp("2021-06-15"), _cfg)
        print(f"Regime 2021-06-15: max_pos={_p2.max_positions}, mult={_p2.position_size_multiplier}")

    replay_kwargs = dict(
        tickers=list(feature_dfs.keys()),
        start=START,
        end=END,
        initial_cash=100_000.0,
        precomputed_features=feature_dfs,
        precomputed_daily_features=daily_features,
        min_entry_score=CONFIG_C["score_threshold"],
        stop_loss_atr_mult=CONFIG_C["stop_atr_mult"],
        max_positions=CONFIG_C["max_positions"],
        max_heat_R=CONFIG_C["max_heat_R"],
        pyramiding_mode=CONFIG_C["pyramiding_mode"],
        risk_per_trade_pct=CONFIG_C["risk_per_trade_pct"],
        cautious_size_mult=CONFIG_C["cautious_size_mult"],
    )

    # Run BASELINE (no MIE)
    print("\n=== Running Config C BASELINE (no MIE) ===")
    t1 = time.time()
    result_base = run_replay(**replay_kwargs, intelligence_enabled=False)
    print(f"Baseline done in {time.time()-t1:.1f}s")
    if result_base:
        print(f"Baseline equity: ${result_base[0].equity:,.2f}")

    # Run with MIE enabled
    print("\n=== Running Config C + MIE Enabled ===")
    t1 = time.time()
    result = run_replay(**replay_kwargs, intelligence_enabled=True)
    print(f"MIE run done in {time.time()-t1:.1f}s")

    if result_base and result:
        print(f"\nBaseline equity: ${result_base[0].equity:,.2f}")
        print(f"MIE equity:     ${result[0].equity:,.2f}")
        print(f"Different: {result_base[0].equity != result[0].equity}")

    if result:
        portfolio, equity_curve, trade_log, _attr = result
        out_dir = "artifacts/runs/config_c_mie"
        os.makedirs(out_dir, exist_ok=True)

        with open(f"{out_dir}/equity_curve.json", "w") as f:
            json.dump(equity_curve, f, indent=2)
        with open(f"{out_dir}/trade_log.json", "w") as f:
            json.dump(trade_log, f, indent=2)
        with open(f"{out_dir}/config.json", "w") as f:
            json.dump({**CONFIG_C, "intelligence_enabled": True}, f, indent=2)

        print(f"\nArtifacts saved to {out_dir}")
    else:
        print("ERROR: No result returned!")


if __name__ == "__main__":
    main()
