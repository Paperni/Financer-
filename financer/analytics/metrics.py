"""Pure metric calculations derived from Canonical Trade Ledgers and Portfolio histories."""

import json
from typing import Any

import pandas as pd


def compute_portfolio_metrics(equity_curve_path: str | None, ledger: pd.DataFrame) -> dict[str, Any]:
    """Calculate aggregate portfolio behavior."""
    metrics = {
        "total_return": 0.0,
        "max_drawdown": 0.0,
        "exposure_pct": 0.0,
        "avg_positions": 0.0,
        "trades_count": len(ledger)
    }
    
    if ledger.empty:
        return metrics
        
    # Estimate total return from PnL if equity curve is mock
    # In a full deployment, we'd parse equity_curve.json to find MDD and Total Return
    total_pnl = ledger["pnl_cash"].sum()
    metrics["total_return"] = total_pnl / 100000.0  # Assumed dummy initial capital
    
    # Calculate a rough Max Drawdown from closed Trades
    cumulative = ledger["pnl_cash"].cumsum()
    running_max = cumulative.cummax()
    drawdowns = (cumulative - running_max) / (100000.0 + running_max)
    metrics["max_drawdown"] = abs(float(drawdowns.min())) if not drawdowns.empty else 0.0
    
    return metrics


def compute_trade_metrics(ledger: pd.DataFrame) -> dict[str, Any]:
    """Calculate statistical edges of all closed trades."""
    if ledger.empty:
        return {
            "win_rate": 0.0,
            "expectancy_R": 0.0,
            "profit_factor": 0.0,
            "avg_win_R": 0.0,
            "avg_loss_R": 0.0,
            "median_hold_bars": 0.0,
            "pnl_R_distribution": {}
        }
        
    wins = ledger[ledger["pnl_R"] > 0]
    losses = ledger[ledger["pnl_R"] <= 0]
    
    win_rate = len(wins) / len(ledger)
    avg_win_r = float(wins["pnl_R"].mean()) if not wins.empty else 0.0
    avg_loss_r = float(losses["pnl_R"].mean()) if not losses.empty else 0.0
    
    profit_factor = abs(wins["pnl_R"].sum() / losses["pnl_R"].sum()) if not losses.empty and losses["pnl_R"].sum() != 0 else float("inf")
    
    expectancy_r = (win_rate * avg_win_r) + ((1 - win_rate) * avg_loss_r)
    
    return {
        "win_rate": float(win_rate),
        "expectancy_R": float(expectancy_r),
        "profit_factor": float(profit_factor),
        "avg_win_R": avg_win_r,
        "avg_loss_R": avg_loss_r,
        "median_hold_bars": float(ledger["hold_bars"].median()),
        "pnl_R_distribution": {
            "p25": float(ledger["pnl_R"].quantile(0.25)),
            "p50": float(ledger["pnl_R"].quantile(0.50)),
            "p75": float(ledger["pnl_R"].quantile(0.75)),
        }
    }


def compute_attribution(ledger: pd.DataFrame, lifecycle_path: str | None = None) -> dict[str, Any]:
    """Slice performace by various categorical drivers."""
    attribution: dict[str, Any] = {
        "by_regime": {},
        "by_entry_score_bucket": {},
        "by_exit_reason": {},
        "top_veto_reasons": {}
    }
    
    if not ledger.empty:
        # By Regime
        if "entry_regime" in ledger.columns:
            regime_grp = ledger.groupby("entry_regime")["pnl_R"].mean().to_dict()
            attribution["by_regime"] = {str(k): float(v) for k, v in regime_grp.items()}

        # By Exit Reason
        exit_grp = ledger.groupby("exit_reason")["pnl_R"].mean().to_dict()
        attribution["by_exit_reason"] = {str(k): float(v) for k, v in exit_grp.items()}
            
    # Parse lifecycle for veto reasons
    if lifecycle_path:
        veto_counts = {}
        try:
            with open(lifecycle_path, "r") as f:
                for line in f:
                    if not line.strip(): continue
                    data = json.loads(line)
                    for veto in data.get("vetoed_intents", []):
                        r = veto.get("reason", "unknown")
                        veto_counts[r] = veto_counts.get(r, 0) + 1
            
            # Top 10 veto reasons
            sorted_vetoes = sorted(veto_counts.items(), key=lambda x: x[1], reverse=True)[:10]
            attribution["top_veto_reasons"] = {k: v for k, v in sorted_vetoes}
        except Exception:
            pass
            
    return attribution
