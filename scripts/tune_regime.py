import os
import json
import itertools
from operator import itemgetter
from datetime import datetime
import sys
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from dataclasses import replace
from legacy.data_static import BROAD_STOCKS, BROAD_ETFS
from financer.cli.run_replay import run_replay
from financer.intelligence.config import load_config
from financer.cli.report_years import run_report_years
from financer.analytics.metrics import compute_max_drawdown_pct

def run_tuning():
    print("--- Phase 2.3 Regime Sweep ---")
    
    # 1. Defined Trajectories
    atr_vol = [0.035, 0.045, 0.055]
    sma_slope = [0.0, 0.0005, 0.001]
    qqq_opts = [False, True]
    
    universe = BROAD_STOCKS + BROAD_ETFS
    
    # Grid search config combos
    configs = list(itertools.product(atr_vol, sma_slope, qqq_opts))
    print(f"Total Sweep Configurations: {len(configs)}")
    
    results = []
    
    # Run Baseline (MIE off) over TRAIN (2021-2024)
    print("\nRunning Baseline Train Window (2021-2024)...")
    base_port, base_eq, _, _ = run_replay(
        tickers=universe,
        start="2021-01-01",
        end="2024-12-31",
        min_entry_score=5.0,  # Config C benchmark
        intelligence_enabled=False,
    )
    base_ret = ((base_port.equity / 100_000.0) - 1.0) * 100.0
    print(f"Baseline Train Return: {base_ret:.2f}%")
    
    print("\nStarting Grid Sweep...")
    
    for idx, (atr, slope, qqq) in enumerate(configs, 1):
        print(f"[{idx}/{len(configs)}] Running config: ATR {atr}, Slope {slope}, QQQ {qqq}...")
        
        base_cfg = load_config()
        new_reg = replace(
            base_cfg.regime,
            atr_vol_threshold=atr,
            sma200_slope_threshold=slope,
            qqq_confirm=qqq
        )
        cfg = replace(base_cfg, regime=new_reg)
        
        port, curve, _, _ = run_replay(
            tickers=universe,
            start="2021-01-01",
            end="2024-12-31",
            min_entry_score=5.0,
            intelligence_enabled=True,
            intelligence_config=cfg,
        )
        
        # Calculate Train Gates
        tot_ret = ((port.equity / 100_000.0) - 1.0) * 100.0
        max_dd = compute_max_drawdown_pct(curve)
        
        # Exposure % calculations
        def get_exposure(year_str):
            y_curve = [pt for pt in curve if pt["date"].startswith(year_str)]
            if not y_curve: return 0.0
            exposed = sum(1 for pt in y_curve if pt.get("utilization_pct", 0) > 0)
            return (exposed / len(y_curve)) * 100.0

        exp_22 = get_exposure("2022")
        
        y23_curve = [pt for pt in curve if pt["date"].startswith("2023")]
        y24_curve = [pt for pt in curve if pt["date"].startswith("2024")]
        combined_23_24 = y23_curve + y24_curve
        exp_23_24 = 0.0
        if combined_23_24:
            exposed_23_24 = sum(1 for pt in combined_23_24 if pt.get("utilization_pct", 0) > 0)
            exp_23_24 = (exposed_23_24 / len(combined_23_24)) * 100.0

        # Regimes Diagnostics
        days = len(curve)
        pct_ro = (sum(1 for pt in curve if pt.get("regime") == "RISK_ON") / days) * 100.0 if days > 0 else 0
        pct_cau = (sum(1 for pt in curve if pt.get("regime") == "CAUTIOUS") / days) * 100.0 if days > 0 else 0
        pct_roff = (sum(1 for pt in curve if pt.get("regime") == "RISK_OFF") / days) * 100.0 if days > 0 else 0
        
        flips = 0
        prev_r = None
        for pt in curve:
            r = pt.get("regime")
            if r and prev_r and r != prev_r:
                flips += 1
            if r:
                prev_r = r

        passed_gates = True
        if max_dd > 15.0: passed_gates = False
        if exp_22 > 70.0: passed_gates = False
        if exp_23_24 < 75.0: passed_gates = False
        if tot_ret < base_ret: passed_gates = False
        
        results.append({
            "idx": idx,
            "atr": atr,
            "slope": slope,
            "qqq": qqq,
            "tot_ret": tot_ret,
            "max_dd": max_dd,
            "exp_22": exp_22,
            "exp_23_24": exp_23_24,
            "pct_ro": pct_ro,
            "pct_cau": pct_cau,
            "pct_roff": pct_roff,
            "flips": flips,
            "passed": passed_gates
        })
        
    print("\n--- SWEEP COMPLETE ---")
    
    passed_results = [r for r in results if r["passed"]]
    passed_results.sort(key=itemgetter("tot_ret"), reverse=True)
    
    print(f"\nTop 5 Configs on TRAIN (Passed Gates):")
    print(f"{'Rank':<5} | {'ATR':<6} | {'Slope':<7} | {'QQQ':<5} | {'Return':<8} | {'MDD':<6} | {'E22':<6} | {'E23_24':<7} | {'%RO':<6} | {'%CAU':<6} | {'%ROFF':<6} | {'Flips'}")
    print("-" * 105)
    for i, res in enumerate(passed_results[:5], 1):
        print(f"#{i:<4} | {res['atr']:<6} | {res['slope']:<7} | {str(res['qqq']):<5} | {res['tot_ret']:>7.2f}% | {res['max_dd']:>5.2f}% | {res['exp_22']:>5.1f}% | {res['exp_23_24']:>6.1f}% | {res['pct_ro']:>5.1f}% | {res['pct_cau']:>5.1f}% | {res['pct_roff']:>5.1f}% | {res['flips']}")
        
    if not passed_results:
        print("No configurations passed the specified gates.")
        # fallback to sort by return out of all
        passed_results = sorted(results, key=itemgetter("tot_ret"), reverse=True)
        print("Showing overall top 3 instead:")
        for i, res in enumerate(passed_results[:3], 1):
            print(f"#{i:<4} | {res['atr']:<6} | {res['slope']:<7} | {str(res['qqq']):<5} | {res['tot_ret']:>7.2f}% | {res['max_dd']:>5.2f}%")

    print("\n\n--- RUNNING TOP 3 ON TEST WINDOW (2025) ---")
    top_3 = passed_results[:3]
    
    for i, res in enumerate(top_3, 1):
        print(f"\nEVALUATING #{i} TEST (ATR: {res['atr']}, Slope: {res['slope']}, QQQ: {res['qqq']})")
        base_test_cfg = load_config()
        new_test_reg = replace(
            base_test_cfg.regime,
            atr_vol_threshold=res['atr'],
            sma200_slope_threshold=res['slope'],
            qqq_confirm=res['qqq']
        )
        cfg = replace(base_test_cfg, regime=new_test_reg)
        out_dir = f"artifacts/test_sweep_rank{i}"
        
        _, curve, trades, mie_attr = run_replay(
            tickers=universe,
            start="2025-01-01",
            end="2025-12-31",
            min_entry_score=5.0,
            intelligence_enabled=True,
            intelligence_config=cfg,
        )
        
        # Save artifacts and run report_years
        from financer.cli.run_replay import save_artifacts
        save_artifacts(curve, trades, mie_attr, output_dir=out_dir)
        run_report_years(out_dir)

if __name__ == "__main__":
    run_tuning()
