import json
from pathlib import Path
import pandas as pd
from financer.features.build import build_features
from financer.cli.run_replay import run_replay
from legacy.data_static import BROAD_STOCKS, BROAD_ETFS
from financer.execution import policy
from financer.models import sizing
from financer.engines.swing import scorecard

# Define the targets
targets = [
    {
        "id": "swing_v1_config_c",
        "start": "2021-01-01",
        "end": "2025-12-31",
        "config": {
            "score_threshold": 5,
            "stop_atr_mult": 1.75,
            "time_stop_bars": 50,
            "rsi_band": [35, 50],
            "cautious_size_mult": 0.75,
            # Defaults for un-provided
            "max_positions": 10,
            "risk_per_trade_pct": 0.01,
            "max_heat_R": 5.0,
            "pyramiding_mode": "off"
        }
    },
    {
        "id": "oos_2025_config_c",
        "start": "2025-01-01",
        "end": "2025-12-31",
        "config": {
            "score_threshold": 5,
            "stop_atr_mult": 1.75,
            "time_stop_bars": 50,
            "rsi_band": [35, 50],
            "cautious_size_mult": 0.75,
            "max_positions": 10,
            "risk_per_trade_pct": 0.01,
            "max_heat_R": 5.0,
            "pyramiding_mode": "off"
        }
    },
    {
        "id": "oos_2025_aggressive",
        "start": "2025-01-01",
        "end": "2025-12-31",
        "config": {
            "score_threshold": 5,
            "stop_atr_mult": 1.75,
            "time_stop_bars": 50,
            "rsi_band": [35, 50],
            "max_positions": 16,
            "risk_per_trade_pct": 0.01,
            "max_heat_R": 7.0,
            "cautious_size_mult": 1.0,
            "pyramiding_mode": "on"
        }
    }
]

def run_target(target):
    run_id = target["id"]
    print(f"\n=== Preparing {run_id} ===")
    start_date = target["start"]
    end_date = target["end"]
    config = target["config"]
    
    tickers = list(dict.fromkeys(BROAD_STOCKS + BROAD_ETFS))
    print(f"Loading features from {start_date} to {end_date}...")
    
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
        max_positions=config.get("max_positions", 10),
        max_heat_R=config.get("max_heat_R", 5.0),
        pyramiding_mode=config.get("pyramiding_mode", "off"),
        risk_per_trade_pct=config.get("risk_per_trade_pct", 0.01),
        cautious_size_mult=config.get("cautious_size_mult", 0.75)
    )
    
    out_dir = Path(f"artifacts/runs/{run_id}")
    out_dir.mkdir(parents=True, exist_ok=True)
    
    with open(out_dir / "config.json", "w") as f:
        json.dump(config, f, indent=2)

    with open(out_dir / "equity_curve.json", "w") as f:
        json.dump(equity_curve, f, indent=2)
        
    with open(out_dir / "trade_log.json", "w") as f:
        json.dump(trade_log, f, indent=2)
        
    print(f"Saved to {out_dir}")

if __name__ == "__main__":
    for t in targets:
        run_target(t)
