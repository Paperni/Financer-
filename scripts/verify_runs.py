import json
import hashlib
from pathlib import Path
import pandas as pd
from financer.features.build import build_features
from financer.cli.run_replay import run_replay
from legacy.data_static import BROAD_STOCKS, BROAD_ETFS
from financer.execution import policy
from financer.models import sizing
from financer.engines.swing import scorecard

def run_config(run_id, config):
    print(f"\n--- Running {run_id} ---")
    print(f"Config: {config}")

    tickers = list(dict.fromkeys(BROAD_STOCKS + BROAD_ETFS))
    start_date = "2021-01-01"
    end_date = "2025-12-31"

    print(f"Loading cached features...")
    feature_dfs = {}
    for ticker in tickers:
        df = build_features(ticker, start=start_date, end=end_date)
        if not df.empty:
            feature_dfs[ticker] = df

    daily_features = {}
    for ticker, df in feature_dfs.items():
        ticker_dict = df.to_dict('index')
        for d, row_dict in ticker_dict.items():
            if pd.isna(d): continue
            ts = pd.to_datetime(d).normalize()
            if ts not in daily_features:
                daily_features[ts] = {}
            daily_features[ts][ticker] = row_dict

    policy.STOP_LOSS_ATR_MULTIPLIER = config["stop_atr_mult"]
    sizing.ATR_STOP_MULTIPLIER = config["stop_atr_mult"]
    policy.TIME_STOP_DAYS = config["time_stop_bars"]
    scorecard.RSI_BAND_LOWER = config["rsi_band"][0]
    scorecard.RSI_BAND_UPPER = config["rsi_band"][1]
    sizing.CAUTIOUS_SIZE_MULT = config["cautious_size_mult"]

    portfolio, equity_curve, trade_log = run_replay(
        tickers=list(feature_dfs.keys()),
        start=start_date,
        end=end_date,
        initial_cash=100000.0,
        min_entry_score=config["score_threshold"],
        stop_loss_atr_mult=config["stop_atr_mult"],
        precomputed_features=feature_dfs,
        precomputed_daily_features=daily_features,
        max_positions=config["max_positions"],
        max_heat_R=config["max_heat_R"],
        pyramiding_mode=config["pyramiding_mode"],
        risk_per_trade_pct=config["risk_per_trade_pct"],
        cautious_size_mult=config["cautious_size_mult"]
    )

    out_dir = Path(f"artifacts/replay/{run_id}")
    out_dir.mkdir(parents=True, exist_ok=True)

    with open(out_dir / "config.json", "w") as f:
        json.dump(config, f, indent=2)

    with open(out_dir / "equity_curve.json", "w") as f:
        json.dump(equity_curve, f, indent=2)

    df_eq = pd.DataFrame(equity_curve)
    start_eq = df_eq['equity'].iloc[0]
    end_eq = df_eq['equity'].iloc[-1]
    recalc_ret = ((end_eq / start_eq) - 1.0) * 100.0
    
    df_eq['peak'] = df_eq['equity'].cummax()
    df_eq['dd'] = (df_eq['peak'] - df_eq['equity']) / df_eq['peak']
    recalc_dd = df_eq['dd'].max() * 100.0

    report = {
        "final_equity": portfolio.equity, 
        "total_return_pct": recalc_ret,
        "max_dd_pct": recalc_dd
    }
    with open(out_dir / "report.json", "w") as f:
        json.dump(report, f, indent=2)

    eq_hash = hashlib.sha256((out_dir / "equity_curve.json").read_bytes()).hexdigest()

    print(f"RUN_ID: {run_id}")
    print(f"Output folder: {out_dir}")
    print(f"equity_curve.json SHA256: {eq_hash}")
    print(f"Recomputed Return %: {recalc_ret:.2f}%")
    print(f"Recomputed Drawdown %: {recalc_dd:.2f}%")
    return eq_hash


if __name__ == "__main__":
    run_a = {
        "score_threshold": 5, "stop_atr_mult": 1.75, "time_stop_bars": 50, "rsi_band": [35, 50],
        "max_positions": 16, "risk_per_trade_pct": 0.01, "max_heat_R": 7.0, "cautious_size_mult": 1.0,
        "pyramiding_mode": "on"
    }

    run_b = {
        "score_threshold": 5, "stop_atr_mult": 1.75, "time_stop_bars": 50, "rsi_band": [35, 50],
        "max_positions": 8, "risk_per_trade_pct": 0.005, "max_heat_R": 3.0, "cautious_size_mult": 1.0,
        "pyramiding_mode": "off"
    }

    hash_a = run_config("RUN_A", run_a)
    hash_b = run_config("RUN_B", run_b)

    if hash_a == hash_b:
        print("\nIDENTICAL HASHES! Mismatch/identity bug confirmed.")
    else:
        print("\nHASHES DIFFER. The deployment parameters are correctly producing distinct simulation paths.")
