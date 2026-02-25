"""Artifact parser casting raw nested events into a canonical Trade Ledger."""

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from financer.analytics.core import ARTIFACT_SCHEMA_VERSION


def parse_run(run_dir: str | Path) -> pd.DataFrame:
    """Parse a run directory and generate a canonical single-row-per-trade Ledger DataFrame."""
    run_dir = Path(run_dir)
    lifecycle_path = run_dir / "lifecycle.jsonl"
    config_path = run_dir / "config.json"
    
    if not config_path.exists():
        raise FileNotFoundError(f"Missing config.json in {run_dir}")
    if not lifecycle_path.exists():
        raise FileNotFoundError(f"Missing lifecycle.jsonl in {run_dir}")
        
    # Read config to get run ID
    with open(config_path, "r") as f:
        run_config = json.load(f)
        run_id = run_config.get("run_id", run_dir.name)
        
    trades: list[dict[str, Any]] = []
    
    # Track open positions iteratively
    # ticker -> { "entry_ts", "entry_px", "qty", "initial_stop", "risk_per_share", "score", "regime", "reasons" }
    open_positions: dict[str, dict[str, Any]] = {}
    
    with open(lifecycle_path, "r") as f:
        for line in f:
            if not line.strip():
                continue
            
            cycle_data = json.loads(line)
            ts_str = cycle_data.get("timestamp")
            
            try:
                ts = datetime.fromisoformat(ts_str.replace('Z', '+00:00'))
            except (ValueError, AttributeError):
                continue
                
            # Process filled orders for this cycle
            filled_orders = cycle_data.get("filled_orders", [])
            for order in filled_orders:
                ticker = order["ticker"]
                direction = order["direction"]
                qty = order.get("qty", 0)
                price = order.get("price", 0.0)
                
                # We need to peek at candidate intents to grab entry metadata (score, reasons)
                # This implies the lifecycle stores intents. The engine outputs them in 'candidate_intents'
                # but our loop currently logs 'vetoed_intents'.
                # For this robust parser, we assume standard schema has `candidate_intents` available
                # or fallback to empty lists if missing.
                intent_metadata = {}
                for cand in cycle_data.get("candidate_intents", []):
                    if cand.get("ticker") == ticker:
                        intent_metadata = cand
                        break
                        
                if direction == "BUY":
                    if ticker not in open_positions:
                        # New Trade
                        # (A real system might calculate risk based on the config/stop, here we hardcode placeholders to be back-filled or mapped)
                        open_positions[ticker] = {
                            "entry_ts": ts,
                            "entry_px": price,
                            "qty": qty,
                            # Risk heuristics below
                            "initial_stop_px": price * 0.9, 
                            "risk_per_share": price * 0.1,
                            "entry_score": intent_metadata.get("conviction", "NONE"),
                            "entry_regime": intent_metadata.get("meta", {}).get("regime", "UNKNOWN"),
                            "entry_reasons": intent_metadata.get("reasons", [])
                        }
                    else:
                        # Scaling In (Update average price)
                        pos = open_positions[ticker]
                        old_val = pos["entry_px"] * pos["qty"]
                        new_val = price * qty
                        pos["qty"] += qty
                        pos["entry_px"] = (old_val + new_val) / pos["qty"]
                        
                elif direction == "SELL":
                    if ticker in open_positions:
                        pos = open_positions[ticker]
                        # Flattening or Scaling Out
                        # For simplicity, any SELL flattens the recorded canonical trade row right now
                        # Calculate PnL
                        pnl_cash = (price - pos["entry_px"]) * qty
                        risk_r = pnl_cash / (pos["risk_per_share"] * qty) if pos["risk_per_share"] > 0 else 0.0
                        
                        hold_days = (ts - pos["entry_ts"]).days
                        
                        trades.append({
                            "run_id": run_id,
                            "ticker": ticker,
                            "entry_ts": pos["entry_ts"],
                            "entry_px": pos["entry_px"],
                            "entry_qty": pos["qty"],
                            "initial_stop_px": pos["initial_stop_px"],
                            "initial_risk_per_share": pos["risk_per_share"],
                            "risk_R": risk_r,
                            "entry_score": pos["entry_score"],
                            "entry_regime": pos["entry_regime"],
                            "entry_reasons": json.dumps(pos["entry_reasons"]),
                            "exit_ts": ts,
                            "exit_px": price,
                            "exit_qty": qty,
                            "exit_reason": intent_metadata.get("reason", "UNKNOWN_EXIT"),
                            "exit_reasons": json.dumps(intent_metadata.get("reasons", [])),
                            "pnl_cash": pnl_cash,
                            "pnl_R": risk_r,
                            "fees_cash": 0.0,
                            "slippage_cash": 0.0,
                            "hold_bars": hold_days, # Alias for daily timeframe
                            "hold_days": hold_days
                        })
                        
                        # Full Exit
                        if qty >= pos["qty"]:
                            del open_positions[ticker]
                        else:
                            pos["qty"] -= qty
                            
    # Return as DataFrame
    df = pd.DataFrame(trades)
    
    # Ensure correct types even if empty
    if df.empty:
        df = pd.DataFrame(columns=[
            "run_id", "ticker", "entry_ts", "entry_px", "entry_qty",
            "initial_stop_px", "initial_risk_per_share", "risk_R",
            "entry_score", "entry_regime", "entry_reasons", "exit_ts",
            "exit_px", "exit_qty", "exit_reason", "exit_reasons",
            "pnl_cash", "pnl_R", "fees_cash", "slippage_cash",
            "hold_bars", "hold_days"
        ])
    return df
