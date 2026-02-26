"""Replay Runner — stepping through history day-by-day.

Flow: Data -> Features -> Swing Engine -> Orchestrator -> SimBroker -> Portfolio.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
import pandas as pd

from financer.features.build import build_features
from financer.engines.swing import SwingEngine, determine_allocation
from financer.core.orchestrator import CIOOrchestrator
from financer.execution.broker_sim import SimBroker
from financer.models.portfolio import PortfolioSnapshot
from financer.models.risk import RiskState
from financer.models.enums import Regime, Direction, Conviction, TimeHorizon
from financer.models.intents import TradeIntent, EngineSource


def run_replay(
    tickers: list[str],
    start: str,
    end: str,
    initial_cash: float = 100_000.0,
    min_entry_score: float = 4.0,
    stop_loss_atr_mult: float = 1.5,
    precomputed_features: dict[str, pd.DataFrame] | None = None,
    precomputed_daily_features: dict[Any, dict[str, dict]] | None = None
):
    """Run a deterministic day-by-day replay simulation."""
    print(f"Loading features for {len(tickers)} tickers from {start} to {end}...")
    
    # 1. Load all features offline
    feature_dfs = {}
    if precomputed_features is not None:
        feature_dfs = precomputed_features
    else:
        for ticker in tickers:
            df = build_features(ticker, start=start, end=end)
            if not df.empty:
                feature_dfs[ticker] = df

    if not feature_dfs and not precomputed_daily_features:
        print("No feature data loaded. Exiting.")
        return None

    # Transpose feature list for O(1) daily lookup
    # Date -> Ticker -> Row
    if precomputed_daily_features is not None:
        daily_features = precomputed_daily_features
    else:
        print("Transposing features for rapid playback...")
        daily_features = {}
        for ticker, df in feature_dfs.items():
            # iterrows is okay here since we only do it once, but to_dict('index') is faster
            ticker_dict = df.to_dict('index')
            for d, row_dict in ticker_dict.items():
                if pd.isna(d): continue
                
                # Normalize timestamp to datetime if needed
                ts = pd.to_datetime(d).normalize()
                if ts not in daily_features:
                    daily_features[ts] = {}
                daily_features[ts][ticker] = row_dict
                
    trading_days = sorted(list(daily_features.keys()))
    print(f"Total trading days to replay: {len(trading_days)}")

    # 2. Boot up core components
    engine = SwingEngine(
        min_entry_score=min_entry_score,
        stop_loss_atr_mult=stop_loss_atr_mult
    )
    orchestrator = CIOOrchestrator()
    broker = SimBroker()
    from financer.execution.position_manager import PositionManager
    pos_manager = PositionManager()
    
    portfolio = PortfolioSnapshot(cash=initial_cash, positions=[])
    risk_state = RiskState(regime=Regime.RISK_ON, open_risk_pct=0.0)
    
    equity_curve = []
    trade_log = []

    # 3. Simulate day-by-day
    for current_day in trading_days:
        day_str = current_day.strftime("%Y-%m-%d")
        
        # O(1) lookup
        latest_features = daily_features.get(current_day, {})

        if not latest_features:
            continue

        # Engine now handles exits. We pass the portfolio.
        for pos in portfolio.positions:
            if pos.ticker in latest_features:
                pos.current_price = float(latest_features[pos.ticker].get("Close", pos.current_price))

        # Update RiskState (Daily mark-to-market)
        risk_op_pct = 0.0
        if portfolio.equity > 0:
            open_risk = sum((pos.current_price - (pos.stop_loss or 0.0)) * pos.qty for pos in portfolio.positions if pos.stop_loss)
            risk_op_pct = open_risk / portfolio.equity
            
        risk_state.open_risk_pct = max(0.0, risk_op_pct)
        risk_state.updated_at = current_day

        # Get Regime from SPY's latest day if available, else RISK_ON
        regime_val = Regime.RISK_ON
        if "SPY" in latest_features:
            regime_str = latest_features["SPY"].get("regime", "RISK_ON")
            try:
                regime_val = Regime(regime_str)
            except ValueError:
                regime_val = Regime.RISK_ON
        risk_state.regime = regime_val

        # Get Intents from Swing Engine
        alloc_intent = determine_allocation(risk_state.regime)
        trade_intents = engine.evaluate(latest_features)
        
        exit_intents, trail_updates = pos_manager.evaluate_exits(portfolio, latest_features, current_day)
        
        # Apply pure trail updates mutations safely here
        for pos in portfolio.positions:
            if pos.ticker in trail_updates:
                pos.stop_loss = trail_updates[pos.ticker]
        
        all_intents = trade_intents + exit_intents
        
        daily_log = {
            "date": day_str,
            "candidate_intents": [],
            "vetoed_intents": [],
            "created_orders": [],
            "filled_orders": []
        }

        if all_intents:
            # We already injected metas in the engine, but orchestrator uses them
            # Check if any missing meta and inject for safety
            for intent in all_intents:
                daily_log["candidate_intents"].append({
                    "ticker": intent.ticker,
                    "direction": intent.direction.value,
                    "conviction": intent.conviction.value,
                    "reasons": [r.code for r in intent.reasons]
                })
                
                if intent.ticker in latest_features and "latest_price" not in intent.meta:
                    intent.meta["latest_price"] = float(latest_features[intent.ticker].get("Close", 100))
                    intent.meta["atr_14"] = float(latest_features[intent.ticker].get("atr_14", 1.0))

            # Formulate Action Plan
            plan = orchestrator.formulate_plan(all_intents, [alloc_intent], portfolio, risk_state)
            
            for vetoed in plan.vetoed_intents:
                daily_log["vetoed_intents"].append({
                    "ticker": vetoed.ticker,
                    "direction": vetoed.direction.value,
                    "reason": vetoed.meta.get("veto_reason", "unknown")
                })
            
            # Execute Plan
            portfolio = broker.execute_plan(plan, portfolio)
            
            # Log Trades
            for order in plan.orders:
                order_dict = {
                    "order_id": order.order_id,
                    "ticker": order.ticker,
                    "direction": order.direction.value,
                    "qty": order.qty,
                    "price": order.price,
                    "status": order.status.value,
                    "reason_codes": order.reason_codes,
                    "veto_reason": order.meta.get("veto_reason", "")
                }
                
                daily_log["created_orders"].append(order_dict)
                if order.status.value == "FILLED":
                    daily_log["filled_orders"].append(order_dict)
                    
        trade_log.append(daily_log)

        # Record daily equity
        equity_curve.append({
            "date": day_str,
            "equity": portfolio.equity,
            "cash": portfolio.cash,
            "drawdown_pct": portfolio.drawdown_pct,
            "utilization_pct": 1.0 - (portfolio.cash / portfolio.equity)
        })

    # Save outputs
    print(f"\nReplay Complete! Final Equity: ${portfolio.equity:,.2f}")
    
    return portfolio, equity_curve, trade_log


def save_artifacts(equity_curve, trade_log, output_dir: str = "artifacts"):
    """Helper to save artifacts."""
    import os
    os.makedirs(output_dir, exist_ok=True)
    
    with open(f"{output_dir}/equity_curve.json", "w") as f:
        json.dump(equity_curve, f, indent=2)
        
    with open(f"{output_dir}/replay_trades.json", "w") as f:
        json.dump(trade_log, f, indent=2)


if __name__ == "__main__":
    portfolio, curve, trades = run_replay(
        tickers=["AAPL", "MSFT", "GOOGL", "SPY"],
        start="2024-01-01",
        end="2024-04-01",
        min_entry_score=3.0  # Loosened parameter as recommended in audit to guarantee trade execution for visibility
    )
    save_artifacts(curve, trades)
