"""Campaign Runner - Orchestrates sweep configurations over specified dates.

Evaluates each configuration and checks it against strict gates.
"""

import itertools
import json
import os
import time
import argparse
import csv
import pandas as pd
import yaml
from pathlib import Path

from financer.execution import policy
from financer.models import sizing
from financer.engines.swing import scorecard
from financer.cli.run_replay import run_replay
from financer.features.build import build_features
from legacy.data_static import BROAD_STOCKS, BROAD_ETFS
from financer.data.prices import get_bars, DataFetchError


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


def write_leaderboard_csv(path, leaderboard):
    if not leaderboard:
        return
    # Flattens config and metrics
    fieldnames = list(leaderboard[0]["config"].keys()) + list(leaderboard[0]["metrics"].keys()) + ["survived", "meets_20pct_target"]
    with open(path, "w", newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in leaderboard:
            out = {**row["config"], **row["metrics"], "survived": row.get("survived", False), "meets_20pct_target": row.get("meets_20pct_target", False)}
            writer.writerow(out)

def write_leaderboard_md(path, survivors):
    with open(path, "w") as f:
        f.write("# Campaign Leaderboard (Survivors)\n\n")
        if not survivors:
            f.write("No configurations survived the gates.\n")
            return
        
        headers = list(survivors[0]["config"].keys()) + ["Ret %", "DD %", "Trades", "ExpR"]
        f.write("| " + " | ".join(headers) + " |\n")
        f.write("| " + " | ".join(["---"] * len(headers)) + " |\n")
        
        for row in survivors:
            c = row["config"]
            m = row["metrics"]
            vals = [str(c[k]) for k in c.keys()] + [
                f"{m['total_return_pct']:.1f}",
                f"{m['max_dd_pct']:.1f}",
                str(m['trades']),
                f"{m['expectancy_R']:.2f}"
            ]
            f.write("| " + " | ".join(vals) + " |\n")


def run_campaign():
    parser = argparse.ArgumentParser(description="Run Campaign Sweep")
    parser.add_argument("--config", required=True, help="Path to campaign YAML config")
    args = parser.parse_args()
    
    with open(args.config, "r") as f:
        cfg = yaml.safe_load(f)
        
    campaign_id = cfg.get("id", "default_campaign")
    
    grid = cfg["sweep_grid"]
    # Handle both rsi_band as list of lists or list of tuples
    keys, values = zip(*grid.items())
    combinations = [dict(zip(keys, v)) for v in itertools.product(*values)]
    
    print(f"Total combinations to sweep: {len(combinations)}")
    
    # Extract universe
    universe_cfg = cfg.get("universe", {})
    if universe_cfg.get("use_broad_lists"):
        tickers = list(dict.fromkeys(BROAD_STOCKS + BROAD_ETFS))
    else:
        tickers = universe_cfg.get("tickers", [])
        
    if "dates" in cfg:
        start_date = cfg["dates"]["start"]
        end_date = cfg["dates"]["end"]
    else:
        start_date = cfg["start"]
        end_date = cfg["end"]
    
    gates = cfg["gates"]
    
    print(f"\n--- PREFLIGHT VALIDATION: Checking {len(tickers)} tickers for active data ---")
    active_tickers = []
    skipped_tickers = []
    
    # Check last 7 days from end_date as preflight
    end_dt = pd.to_datetime(end_date)
    preflight_start = (end_dt - pd.Timedelta(days=7)).strftime("%Y-%m-%d")
    
    for i, ticker in enumerate(tickers, 1):
        try:
            bars = get_bars(ticker, start=preflight_start, end=end_date)
            if bars.empty:
                skipped_tickers.append((ticker, "Empty or dead ticker"))
            else:
                active_tickers.append(ticker)
        except DataFetchError as e:
            skipped_tickers.append((ticker, str(e)))
        
        if i % 25 == 0 or i == len(tickers):
            print(f"Preflight Progress: {i}/{len(tickers)} (Active: {len(active_tickers)}, Skipped: {len(skipped_tickers)})")
            
    tickers = active_tickers
    print(f"Preflight complete. {len(tickers)} tickers active. {len(skipped_tickers)} skipped.\n")

    print(f"Precomputing features for {len(tickers)} active tickers from {start_date} to {end_date}...")
    t_start = time.time()
    feature_dfs = {}
    
    ok_count = 0
    err_count = 0
    for i, ticker in enumerate(tickers, 1):
        try:
            df = build_features(ticker, start=start_date, end=end_date)
            if not df.empty:
                feature_dfs[ticker] = df
                ok_count += 1
            else:
                skipped_tickers.append((ticker, "Feature build returned empty"))
                err_count += 1
        except DataFetchError as e:
            skipped_tickers.append((ticker, str(e)))
            err_count += 1
            
        if i % 25 == 0 or i == len(tickers):
            print(f"Feature Build Progress: {i}/{len(tickers)} (OK: {ok_count}, Err: {err_count})")
            
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
        # Build dynamic kwargs matching supported run_replay arguments
        kwargs = {
            "tickers": list(feature_dfs.keys()),
            "start": start_date,
            "end": end_date,
            "initial_cash": 100000.0,
            "precomputed_features": feature_dfs,
            "precomputed_daily_features": daily_features,
            "min_entry_score": comb.get("score_threshold", 5),
            "stop_loss_atr_mult": comb.get("stop_atr_mult", 1.5),
        }
        
        # Inject optional sweep grid parameters if defined
        for optional_key in ["max_positions", "max_heat_R", "pyramiding_mode", "risk_per_trade_pct", "cautious_size_mult"]:
            if optional_key in comb:
                kwargs[optional_key] = comb[optional_key]
                
        result = run_replay(**kwargs)
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
            "metrics": metrics,
            "meets_20pct_target": bool(metrics["total_return_pct"] >= 20.0 and metrics["max_dd_pct"] <= 15.0)
        }
        
        leaderboard.append(record)
        
    print(f"\nCompleted {len(combinations)} runs.")
    
    # 4. Filter by Gates
    survivors = []
    print("\n--- Survived Gates ---")
    for rec in leaderboard:
        m = rec["metrics"]
        if (m["trades"] >= gates.get("min_trades", 0) and 
            m["max_dd_pct"] <= gates.get("max_dd_pct", 100.0) and 
            m["expectancy_R"] >= gates.get("min_expectancy_R", 0.0)):
            rec["survived"] = True
            survivors.append(rec)
            print(f"Config: {rec['config']}")
            print(f"  -> Ret: {m['total_return_pct']:.1f}%, DD: {m['max_dd_pct']:.1f}%, Trades: {m['trades']}, ExpR: {m['expectancy_R']:.2f}")
        else:
            rec["survived"] = False
            
    print(f"\nSurvived: {len(survivors)} / {len(combinations)}")
    
    # Save results
    out_dir = Path("artifacts") / "campaigns" / campaign_id
    out_dir.mkdir(parents=True, exist_ok=True)
    
    out_summary = out_dir / "summary.json"
    with open(out_summary, "w") as f:
        json.dump({"leaderboard": leaderboard, "survivors": survivors}, f, indent=2)
        
    write_leaderboard_csv(out_dir / "leaderboard.csv", leaderboard)
    write_leaderboard_md(out_dir / "leaderboard.md", survivors)
    
    if skipped_tickers:
        with open(out_dir / "skipped_tickers.csv", "w", newline='') as f:
            writer = csv.writer(f)
            writer.writerow(["Ticker", "Reason"])
            writer.writerows(skipped_tickers)
    
    print("\n" + "="*60)
    print("CAMPAIGN SIMULATION COMPLETELY FINISHED!")
    print(f"Saved all artifacts and results to {out_dir}")
    if skipped_tickers:
        print(f"WARNING: {len(skipped_tickers)} tickers were skipped. See skipped_tickers.csv")
    print("="*60 + "\n")


if __name__ == "__main__":
    run_campaign()
