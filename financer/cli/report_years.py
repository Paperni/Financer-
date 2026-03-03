import argparse
import json
import logging
from pathlib import Path
import pandas as pd
from datetime import datetime
from financer.analytics.metrics import compute_max_drawdown_pct

logging.basicConfig(level=logging.INFO)

def run_report_years(run_dir: str):
    dir_path = Path(run_dir)
    eq_path = dir_path / "equity_curve.json"
    ledger_path = dir_path / "ledger.csv"
    
    if not eq_path.exists():
        print(f"Error: {eq_path} not found.")
        return
        
    with open(eq_path, "r") as f:
        equity_curve = json.load(f)
        
    ledger_df = pd.DataFrame()
    if ledger_path.exists():
        ledger_df = pd.read_csv(ledger_path)
    
    # Pre-parse ledger trades
    # To compute expectancy_R for trades closed in that year, we need to match buys/sells.
    # Actually, we can just simulate the closed trades logic from run_campaign.py
    with open(dir_path / "config.json", "r") as f:
        config = json.load(f)
        
    # Replay trades from trade_log.json if exists, else ledger
    # Re-using the logic to find closed trades
    trade_log_path = dir_path / "trade_log.json"
    closed_trades_by_year = {}
    
    if trade_log_path.exists():
        with open(trade_log_path, "r") as f:
            trade_log = json.load(f)
            
        open_pos = {}
        for cycle in trade_log:
            cycle_date = cycle["date"]
            year = cycle_date[:4]
            if year not in closed_trades_by_year:
                closed_trades_by_year[year] = []
                
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
                            r_multiple = profit_pct / 0.10
                            closed_trades_by_year[year].append({
                                "profit_pct": profit_pct,
                                "r_multiple": r_multiple
                            })
                        if order["qty"] >= pos["qty"]:
                            del open_pos[ticker]
                        else:
                            pos["qty"] -= order["qty"]
    
    # Group equity points by year
    years_data = {}
    for pt in equity_curve:
        dt = pt["date"]
        # handle different date formats just in case
        if "T" in dt:
            year = dt.split("-")[0]
        else:
            year = dt[:4]
            
        if year not in years_data:
            years_data[year] = []
        years_data[year].append(pt)
        
    print(f"\nYear-By-Year Breakdown for: {run_dir}")
    print(f"{'Year':<6} | {'Return %':<10} | {'Max DD %':<10} | {'Trades':<8} | {'Exp R':<8} | {'Exposure %':<11} | {'% RISK_ON':<10} | {'% CAUTIOUS':<11} | {'% RISK_OFF':<11} | {'Flips'}")
    print("-" * 115)
    
    for year in sorted(years_data.keys()):
        curve = years_data[year]
        if not curve:
            continue
            
        start_eq = curve[0]["equity"]
        end_eq = curve[-1]["equity"]
        ret_pct = ((end_eq - start_eq) / start_eq) * 100.0 if start_eq > 0 else 0.0
        
        mdd_pct = compute_max_drawdown_pct(curve)
        
        # Exposure % = fraction of days with utilization_pct > 0
        days = len(curve)
        exposed_days = sum(1 for pt in curve if pt.get("utilization_pct", 0) > 0)
        exposure_pct = (exposed_days / days) * 100.0 if days > 0 else 0.0
        
        year_trades = closed_trades_by_year.get(year, [])
        trades_count = len(year_trades)
        
        exp_r = 0.0
        if trades_count > 0:
            win_rate = sum(1 for t in year_trades if t["profit_pct"] > 0) / trades_count
            wins = [t["r_multiple"] for t in year_trades if t["profit_pct"] > 0]
            losses = [t["r_multiple"] for t in year_trades if t["profit_pct"] <= 0]
            avg_win = sum(wins) / len(wins) if wins else 0.0
            avg_loss = sum(losses) / len(losses) if losses else 0.0
            exp_r = (win_rate * avg_win) + ((1 - win_rate) * avg_loss)
            
        # Count Regimes
        ro_days = sum(1 for pt in curve if pt.get("regime") == "RISK_ON")
        cau_days = sum(1 for pt in curve if pt.get("regime") == "CAUTIOUS")
        roff_days = sum(1 for pt in curve if pt.get("regime") == "RISK_OFF")
        
        pct_ro = (ro_days / days) * 100.0 if days > 0 else 0.0
        pct_cau = (cau_days / days) * 100.0 if days > 0 else 0.0
        pct_roff = (roff_days / days) * 100.0 if days > 0 else 0.0
        
        flips = 0
        prev_r = None
        for pt in curve:
            r = pt.get("regime")
            if r and prev_r and r != prev_r:
                flips += 1
            if r:
                prev_r = r
                
        # If no regime tracking was saved, skip printing the columns
        if ro_days == 0 and cau_days == 0 and roff_days == 0:
            print(f"{year:<6} | {ret_pct:>9.2f}% | {mdd_pct:>9.2f}% | {trades_count:>6} | {exp_r:>6.2f} | {exposure_pct:>9.2f}%")
        else:
            print(f"{year:<6} | {ret_pct:>9.2f}% | {mdd_pct:>9.2f}% | {trades_count:>6} | {exp_r:>6.2f} | {exposure_pct:>9.2f}% | {pct_ro:>9.1f}% | {pct_cau:>10.1f}% | {pct_roff:>10.1f}% | {flips:>4}")
        
    print("-" * 115)
    # Print total
    overall_start = equity_curve[0]["equity"]
    overall_end = equity_curve[-1]["equity"]
    tot_ret = ((overall_end - overall_start) / overall_start) * 100.0
    tot_mdd = compute_max_drawdown_pct(equity_curve)
    
    tot_trades = sum(len(yr) for yr in closed_trades_by_year.values())
    all_trades = []
    for yr in closed_trades_by_year.values():
        all_trades.extend(yr)
        
    tot_exp = 0.0
    if tot_trades > 0:
        win_rate = sum(1 for t in all_trades if t["profit_pct"] > 0) / tot_trades
        wins = [t["r_multiple"] for t in all_trades if t["profit_pct"] > 0]
        losses = [t["r_multiple"] for t in all_trades if t["profit_pct"] <= 0]
        avg_win = sum(wins) / len(wins) if wins else 0.0
        avg_loss = sum(losses) / len(losses) if losses else 0.0
        tot_exp = (win_rate * avg_win) + ((1 - win_rate) * avg_loss)
        
    tot_days = len(equity_curve)
    tot_exposed = sum(1 for pt in equity_curve if pt.get("utilization_pct", 0) > 0)
    tot_exposure = (tot_exposed / tot_days) * 100.0 if tot_days > 0 else 0.0
    
    tot_ro_days = sum(1 for pt in equity_curve if pt.get("regime") == "RISK_ON")
    tot_cau_days = sum(1 for pt in equity_curve if pt.get("regime") == "CAUTIOUS")
    tot_roff_days = sum(1 for pt in equity_curve if pt.get("regime") == "RISK_OFF")
    
    t_pct_ro = (tot_ro_days / tot_days) * 100.0 if tot_days > 0 else 0.0
    t_pct_cau = (tot_cau_days / tot_days) * 100.0 if tot_days > 0 else 0.0
    t_pct_roff = (tot_roff_days / tot_days) * 100.0 if tot_days > 0 else 0.0
    
    tot_flips = 0
    prev_r = None
    for pt in equity_curve:
        r = pt.get("regime")
        if r and prev_r and r != prev_r:
            tot_flips += 1
        if r:
            prev_r = r

    if tot_ro_days == 0 and tot_cau_days == 0 and tot_roff_days == 0:
        print(f"{'TOTAL':<6} | {tot_ret:>9.2f}% | {tot_mdd:>9.2f}% | {tot_trades:>6} | {tot_exp:>6.2f} | {tot_exposure:>9.2f}%")
    else:
        print(f"{'TOTAL':<6} | {tot_ret:>9.2f}% | {tot_mdd:>9.2f}% | {tot_trades:>6} | {tot_exp:>6.2f} | {tot_exposure:>9.2f}% | {t_pct_ro:>9.1f}% | {t_pct_cau:>10.1f}% | {t_pct_roff:>10.1f}% | {tot_flips:>4}")
    print("\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", required=True, help="Directory path to the replay execution")
    args = parser.parse_args()
    
    run_report_years(args.run)
