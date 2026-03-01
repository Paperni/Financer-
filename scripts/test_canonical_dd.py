import json
import logging
from financer.analytics.metrics import compute_max_drawdown_pct

print("--- CANONICAL DD VERIFICATION ---")
for run in ["RUN_A", "RUN_B"]:
    with open(f"artifacts/replay/{run}/equity_curve.json") as f:
        eq = json.load(f)
    with open(f"artifacts/replay/{run}/report.json") as f:
        rep = json.load(f)
        
    prev_dd = rep.get("max_dd_pct", 0.0)
    new_dd = compute_max_drawdown_pct(eq)
    
    print(f"{run}:")
    print(f"  Previous max_dd_pct: {prev_dd:.2f}%")
    print(f"  New canonical max_dd: {new_dd:.2f}%")
    print()
