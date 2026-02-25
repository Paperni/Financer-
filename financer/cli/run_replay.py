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
    min_entry_score: float = 4.0
):
    """Run a deterministic day-by-day replay simulation."""
    print(f"Loading features for {len(tickers)} tickers from {start} to {end}...")
    
    # 1. Load all features offline
    feature_dfs = {}
    for ticker in tickers:
        df = build_features(ticker, start=start, end=end)
        if not df.empty:
            feature_dfs[ticker] = df

    if not feature_dfs:
        print("No feature data loaded. Exiting.")
        return None

    # Find the union of all trading days
    all_dates = set()
    for df in feature_dfs.values():
        all_dates.update(df.index.normalize())
    
    trading_days = sorted(list(all_dates))
    
    print(f"Total trading days to replay: {len(trading_days)}")

    # 2. Boot up core components
    engine = SwingEngine(min_entry_score=min_entry_score)
    orchestrator = CIOOrchestrator()
    broker = SimBroker()
    
    portfolio = PortfolioSnapshot(cash=initial_cash, positions=[])
    risk_state = RiskState(regime=Regime.RISK_ON, open_risk_pct=0.0)
    
    equity_curve = []
    trade_log = []

    # 3. Simulate day-by-day
    for current_day in trading_days:
        day_str = current_day.strftime("%Y-%m-%d")
        
        # Build "latest" features row for the current day
        latest_features = {}
        for ticker, df in feature_dfs.items():
            if current_day in df.index:
                row = df.loc[current_day]
                latest_features[ticker] = row

        if not latest_features:
            continue

        # Very basic mock-logic to exit positions if simulated SL/TP is hit
        # In a real system, the broker or a dedicated Risk Engine handles exit intents
        exit_intents = []
        for pos in portfolio.positions:
            if pos.ticker in latest_features:
                curr_price = float(latest_features[pos.ticker].get("Close", pos.current_price))
                pos.current_price = curr_price  # Mark to market
                
                # Check limits
                hit_sl = pos.stop_loss and curr_price <= pos.stop_loss
                hit_tp = pos.take_profit_1 and curr_price >= pos.take_profit_1
                
                if hit_sl or hit_tp:
                    exit_intents.append(
                        TradeIntent(
                            ticker=pos.ticker,
                            direction=Direction.SELL,
                            conviction=Conviction.HIGH,
                            time_horizon=TimeHorizon.SWING,
                            source=EngineSource.SWING,
                            reasons=[],
                            meta={"latest_price": curr_price}
                        )
                    )

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
        
        # Combine Engine entries with our synthetic SL/TP exits
        all_intents = trade_intents + exit_intents

        if all_intents:
            # Inject current price into metas for Orchestrator sizing
            for intent in all_intents:
                if intent.ticker in latest_features:
                    intent.meta["latest_price"] = float(latest_features[intent.ticker].get("Close", 100))
                    intent.meta["atr_14"] = float(latest_features[intent.ticker].get("atr_14", 1.0))

            # Formulate Action Plan
            plan = orchestrator.formulate_plan(all_intents, [alloc_intent], portfolio, risk_state)
            
            # Execute Plan
            portfolio = broker.execute_plan(plan, portfolio)
            
            # Log Trades
            for order in plan.orders:
                trade_log.append({
                    "date": day_str,
                    "order_id": order.order_id,
                    "ticker": order.ticker,
                    "direction": order.direction.value,
                    "qty": order.qty,
                    "price": order.price,
                    "status": order.status.value,
                    "reason_codes": order.reason_codes,
                    "veto_reason": order.meta.get("veto_reason", "")
                })

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
    
    with open("equity_curve.json", "w") as f:
        json.dump(equity_curve, f, indent=2)
        
    with open("test_results/replay_trades.json", "w") as f:
        json.dump(trade_log, f, indent=2)
        
    return portfolio, equity_curve, trade_log


if __name__ == "__main__":
    # Ensure standard dirs exist
    import os
    os.makedirs("test_results", exist_ok=True)
    
    run_replay(
        tickers=["AAPL", "MSFT", "GOOGL", "SPY"],
        start="2024-01-01",
        end="2024-04-01",
        min_entry_score=3.0  # Loosened parameter as recommended in audit to guarantee trade execution for visibility
    )
