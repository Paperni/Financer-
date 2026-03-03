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
from financer.models.intents import ReasonCode, TradeIntent, EngineSource


def run_replay(
    tickers: list[str],
    start: str,
    end: str,
    initial_cash: float = 100_000.0,
    min_entry_score: float = 4.0,
    stop_loss_atr_mult: float = 1.5,
    precomputed_features: dict[str, pd.DataFrame] | None = None,
    precomputed_daily_features: dict[Any, dict[str, dict]] | None = None,
    max_positions: int = 20,
    max_heat_R: float = 5.0,
    pyramiding_mode: str = "off",
    risk_per_trade_pct: float | None = None,
    cautious_size_mult: float = 0.75,
    intelligence_enabled: bool = False,
    intelligence_config=None,
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
                
    # Restrict execution to [start, end] — warmup data may exist in
    # daily_features for indicator computation but must not be traded on.
    start_ts = pd.Timestamp(start, tz="UTC").normalize()
    end_ts = pd.Timestamp(end, tz="UTC").normalize()
    trading_days = sorted(
        d for d in daily_features.keys()
        if start_ts <= d.normalize() <= end_ts
    )
    print(f"Total trading days to replay: {len(trading_days)} (window {start} to {end})")

    # 2. Boot up core components
    engine = SwingEngine(
        min_entry_score=min_entry_score,
        stop_loss_atr_mult=stop_loss_atr_mult
    )
    from financer.core.governor import RiskGovernor
    governor = RiskGovernor(
        max_positions=max_positions,
        max_heat_R=max_heat_R,
        pyramiding_mode=pyramiding_mode
    )
    orchestrator = CIOOrchestrator(
        governor=governor,
        cautious_size_mult=cautious_size_mult,
        risk_per_trade_pct=risk_per_trade_pct
    )
    broker = SimBroker()
    from financer.execution.position_manager import PositionManager
    pos_manager = PositionManager()
    
    portfolio = PortfolioSnapshot(cash=initial_cash, positions=[])
    risk_state = RiskState(regime=Regime.RISK_ON, open_risk_pct=0.0)

    # Intelligence engine setup (lazy imports to keep MIE optional)
    intel_config = None
    regime_smoothing = None
    if intelligence_enabled:
        from financer.intelligence.config import load_config as load_intel_config
        from financer.intelligence.regime import _RegimeSmoothing
        intel_config = intelligence_config if intelligence_config is not None else load_intel_config()
        regime_smoothing = _RegimeSmoothing()

    equity_curve = []
    trade_log = []

    # MIE attribution tracking
    mie_attribution: dict = {
        "regime_days": {"RISK_ON": 0, "CAUTIOUS": 0, "RISK_OFF": 0},
        "entry_intents_total": 0,
        "entry_intents_vetoed_by_mie": 0,
        "exits_forced_by_mie": 0,
        "forced_exit_tickers": [],
        "scorecard_thresholds": [],
        "position_size_multipliers": [],
    }

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
                pos.current_price = float(latest_features[pos.ticker].get("close", pos.current_price))

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

        # Generate ControlPlan from intelligence if enabled
        control_plan = None
        if intelligence_enabled and intel_config is not None:
            from financer.intelligence.regime import classify_regime_at_date
            spy_df = feature_dfs.get("SPY")
            if spy_df is None and precomputed_features is not None:
                spy_df = precomputed_features.get("SPY")
                
            qqq_df = feature_dfs.get("QQQ")
            if qqq_df is None and precomputed_features is not None:
                qqq_df = precomputed_features.get("QQQ")
                
            if spy_df is not None:
                control_plan = classify_regime_at_date(
                    spy_df, current_day, intel_config, smoothing=regime_smoothing, qqq_df=qqq_df
                )
                
                # Track regime flips
                if previous_plan_regime is not None and control_plan.state.regime != previous_plan_regime:
                    mie_attribution["regime_flips"] += 1
                previous_plan_regime = control_plan.state.regime
                
                if control_plan.policy.allow_entries:
                    # Override engine score threshold for this cycle
                    engine.min_entry_score = control_plan.scorecard_threshold
                    mie_attribution["scorecard_thresholds"].append(control_plan.scorecard_threshold)
                    mie_attribution["position_size_multipliers"].append(control_plan.position_size_multiplier)
                
                # Track attribution
                regime_name = control_plan.regime.value
                if regime_name in mie_attribution["regime_days"]:
                    mie_attribution["regime_days"][regime_name] += 1
            else:
                engine.min_entry_score = min_entry_score
        else:
            engine.min_entry_score = min_entry_score

        # Get Intents from Swing Engine
        alloc_intent = determine_allocation(risk_state.regime)
        if control_plan is None or control_plan.policy.allow_entries:
            trade_intents = engine.evaluate(latest_features)
        else:
            trade_intents = []

        # Track entry intents for attribution
        entry_intents_today = [i for i in trade_intents if i.direction == Direction.BUY]
        mie_attribution["entry_intents_total"] += len(entry_intents_today)

        exit_intents, trail_updates = pos_manager.evaluate_exits(portfolio, latest_features, current_day)

        # Apply pure trail updates mutations safely here
        for pos in portfolio.positions:
            if pos.ticker in trail_updates:
                pos.stop_loss = trail_updates[pos.ticker]

        # RISK_OFF emergency exits: only auto-flatten if crash_flag is set
        if control_plan is not None and control_plan.max_positions == 0 and getattr(control_plan, 'crash_flag', False):
            exited_tickers = {ei.ticker for ei in exit_intents}
            for pos in portfolio.positions:
                if pos.ticker not in exited_tickers:
                    curr = float(latest_features.get(pos.ticker, {}).get("close", pos.current_price))
                    exit_intents.append(TradeIntent(
                        ticker=pos.ticker,
                        direction=Direction.SELL,
                        conviction=Conviction.HIGH,
                        time_horizon=TimeHorizon.SWING,
                        source=EngineSource.SWING,
                        reasons=[ReasonCode(code="REGIME_EXIT", detail="RISK_OFF regime exit")],
                        meta={"latest_price": curr},
                    ))
                    mie_attribution["exits_forced_by_mie"] += 1
                    mie_attribution["forced_exit_tickers"].append(pos.ticker)

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
                    intent.meta["latest_price"] = float(latest_features[intent.ticker].get("close", 100))
                    intent.meta["atr_14"] = float(latest_features[intent.ticker].get("atr_14", 1.0))

            # Formulate Action Plan
            plan = orchestrator.formulate_plan(all_intents, [alloc_intent], portfolio, risk_state, control_plan=control_plan)
            
            for vetoed in plan.vetoed_intents:
                daily_log["vetoed_intents"].append({
                    "ticker": vetoed.ticker,
                    "direction": vetoed.direction.value,
                    "reason": vetoed.meta.get("veto_reason", "unknown")
                })
            
            # Execute Plan
            portfolio = broker.execute_plan(plan, portfolio, current_date=current_day)
            
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
            "utilization_pct": 1.0 - (portfolio.cash / portfolio.equity),
            "regime": risk_state.regime.value if risk_state.regime else "RISK_ON",
        })

    # Save outputs
    print(f"\nReplay Complete! Final Equity: ${portfolio.equity:,.2f}")

    # Count vetoed BUY intents from trade_log (MIE attribution)
    for day in trade_log:
        for v in day.get("vetoed_intents", []):
            if v.get("direction") == "BUY":
                mie_attribution["entry_intents_vetoed_by_mie"] += 1

    return portfolio, equity_curve, trade_log, mie_attribution


def save_artifacts(equity_curve, trade_log, mie_attribution=None, output_dir: str = "artifacts"):
    """Helper to save artifacts."""
    import os
    os.makedirs(output_dir, exist_ok=True)
    
    with open(f"{output_dir}/equity_curve.json", "w") as f:
        json.dump(equity_curve, f, indent=2)
        
    with open(f"{output_dir}/replay_trades.json", "w") as f:
        json.dump(trade_log, f, indent=2)
        
    if mie_attribution:
        with open(f"{output_dir}/mie_attribution.json", "w") as f:
            json.dump(mie_attribution, f, indent=2)


if __name__ == "__main__":
    portfolio, curve, trades, mie_attr = run_replay(
        tickers=["AAPL", "MSFT", "GOOGL", "SPY"],
        start="2024-01-01",
        end="2024-04-01",
        min_entry_score=3.0  # Loosened parameter as recommended in audit to guarantee trade execution for visibility
    )
    save_artifacts(curve, trades, mie_attribution=mie_attr)
