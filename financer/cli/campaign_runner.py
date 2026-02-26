"""Campaign Runner - Orchestrates 48 sweep configurations over 5 years.

Evaluates each configuration and checks it against strict gates:
- min_trades: 60
- max_dd_pct: 15%
- min_expectancy_R: 0.10
"""

import itertools
import json
import os
import time
import pandas as pd
from pathlib import Path

from financer.execution import policy
from financer.models import sizing
from financer.engines.swing import scorecard
from financer.cli.run_replay import run_replay
from financer.features.build import build_features
from legacy.data_static import BROAD_STOCKS, BROAD_ETFS


def compute_metrics(equity_curve: list, trade_log: list) -> dict:
    if not equity_curve:
        return {"max_dd_pct": 0.0, "trades": 0, "expectancy_R": 0.0}
        
    max_dd = max(pt.get("drawdown_pct", 0) for pt in equity_curve) * 100.0
    
    open_pos = {}
    completed_trades = []
    
    for cycle in trade_log:
        for order in cycle.get("filled_orders", []):
            ticker = order["ticker"]
            if order["direction"] == "BUY":
                if ticker not in open_pos:
                    open_pos[ticker] = {"entry": order["price"], "qty": order["qty"]}
                else:
                    pos = open_pos[ticker]
                    new_qty = pos["qty"] + order["qty"]
                    if new_qty > 0:
                        pos["entry"] = ((pos["entry"] * pos["qty"]) + (order["price"] * order["qty"])) / new_qty
                    pos["qty"] = new_qty
            elif order["direction"] == "SELL":
                if ticker in open_pos:
                    pos = open_pos[ticker]
                    if pos["entry"] > 0:
                        profit_pct = (order["price"] - pos["entry"]) / pos["entry"]
                        # Assume 1R is 10% move for nominal expectancy calculations
                        r_multiple = profit_pct / 0.10
                        
                        completed_trades.append({
                            "profit_pct": profit_pct,
                            "r_multiple": r_multiple
                        })
                    
                    if order["qty"] >= pos["qty"]:
                        del open_pos[ticker]
                    else:
                        pos["qty"] -= order["qty"]
                        
    trades_count = len(completed_trades)
    
    if trades_count == 0:
        return {"max_dd_pct": max_dd, "trades": 0, "expectancy_R": 0.0}
        
    win_rate = sum(1 for t in completed_trades if t["profit_pct"] > 0) / trades_count
    
    wins = [t["r_multiple"] for t in completed_trades if t["profit_pct"] > 0]
    losses = [t["r_multiple"] for t in completed_trades if t["profit_pct"] <= 0]
    
    avg_win = sum(wins) / len(wins) if wins else 0.0
    avg_loss = sum(losses) / len(losses) if losses else 0.0
    
    expectancy_R = (win_rate * avg_win) + ((1 - win_rate) * avg_loss)
    
    return {
        "max_dd_pct": max_dd,
        "trades": trades_count,
        "expectancy_R": expectancy_R
    }


def run_campaign():
    grid = {
        "score_threshold": [5, 6],
        "stop_atr_mult": [1.25, 1.5, 1.75],
        "time_stop_bars": [30, 50],
        "rsi_band": [(30, 45), (35, 50)],
        "cautious_size_mult": [0.5, 0.75],
    }
    
    keys, values = zip(*grid.items())
    combinations = [dict(zip(keys, v)) for v in itertools.product(*values)]
    
    print(f"Total combinations to sweep: {len(combinations)}")
    
    tickers = list(dict.fromkeys(BROAD_STOCKS + BROAD_ETFS))
    start_date = "2021-01-01"
    end_date = "2025-12-31"
    
    print(f"\nPrecomputing features for {len(tickers)} tickers across 5 years...")
    t_start = time.time()
    feature_dfs = {}
    for ticker in tickers:
        df = build_features(ticker, start=start_date, end=end_date)
        if not df.empty:
            feature_dfs[ticker] = df
    print(f"Precomputation done in {time.time() - t_start:.2f}s.\n")
    
    print("Transposing features for rapid array playback...")
    t_trans = time.time()
    daily_features = {}
    for ticker, df in feature_dfs.items():
        ticker_dict = df.to_dict('index')
        for d, row_dict in ticker_dict.items():
            if pd.isna(d): continue
            ts = pd.to_datetime(d).normalize()
            if ts not in daily_features:
                daily_features[ts] = {}
            daily_features[ts][ticker] = row_dict
    print(f"Transposition done in {time.time() - t_trans:.2f}s.\n")
    
    leaderboard = []
    
    for i, comb in enumerate(combinations, 1):
        print(f"\n[{i}/{len(combinations)}] Running config: {comb}")
        
        # 1. Patch globals
        policy.STOP_LOSS_ATR_MULTIPLIER = comb["stop_atr_mult"]
        sizing.ATR_STOP_MULTIPLIER = comb["stop_atr_mult"]
        policy.TIME_STOP_DAYS = comb["time_stop_bars"]
        scorecard.RSI_BAND_LOWER = comb["rsi_band"][0]
        scorecard.RSI_BAND_UPPER = comb["rsi_band"][1]
        sizing.CAUTIOUS_SIZE_MULT = comb["cautious_size_mult"]
        
        # 2. Run simulation
        t0 = time.time()
        result = run_replay(
            tickers=tickers,
            start=start_date,
            end=end_date,
            initial_cash=100000.0,
            min_entry_score=comb["score_threshold"],
            stop_loss_atr_mult=comb["stop_atr_mult"],
            precomputed_daily_features=daily_features
        )
        t1 = time.time()
        
        if not result:
            print("  No result returned.")
            continue
            
        portfolio, equity_curve, trade_log = result
        
        # 3. Compute Metrics
        metrics = compute_metrics(equity_curve, trade_log)
        metrics["total_return_pct"] = ((portfolio.equity / 100000.0) - 1.0) * 100.0
        
        print(f"  Result: Trades={metrics['trades']}, DD={metrics['max_dd_pct']:.1f}%, ExprR={metrics['expectancy_R']:.2f}, Ret={metrics['total_return_pct']:.1f}% (Time: {t1-t0:.1f}s)")
        
        record = {
            "config": comb,
            "metrics": metrics
        }
        
        leaderboard.append(record)
        
    print(f"\nCompleted {len(combinations)} runs.")
    
    # 4. Filter by Gates
    survivors = []
    print("\n--- Survived Gates ---")
    for rec in leaderboard:
        m = rec["metrics"]
        if m["trades"] >= 60 and m["max_dd_pct"] <= 15.0 and m["expectancy_R"] >= 0.10:
            survivors.append(rec)
            print(f"Config: {rec['config']}")
            print(f"  -> Ret: {m['total_return_pct']:.1f}%, DD: {m['max_dd_pct']:.1f}%, Trades: {m['trades']}, ExpR: {m['expectancy_R']:.2f}")
            
    print(f"\nSurvived: {len(survivors)} / {len(combinations)}")
    
    # Save results
    os.makedirs("artifacts", exist_ok=True)
    with open("artifacts/campaign_results.json", "w") as f:
        json.dump({"leaderboard": leaderboard, "survivors": survivors}, f, indent=2)
    print("Saved to artifacts/campaign_results.json")


if __name__ == "__main__":
    run_campaign()
