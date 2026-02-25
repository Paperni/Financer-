"""CIO Orchestrator — the central brain that routes intents to actions."""

from __future__ import annotations

from financer.models.actions import ActionPlan, Order
from financer.models.intents import AllocationIntent, TradeIntent
from financer.models.portfolio import PortfolioSnapshot
from financer.models.risk import RiskState
from financer.models.sizing import position_size

from .governor import RiskGovernor


class CIOOrchestrator:
    """Translates Engine Intents into concrete ActionPlans."""

    def __init__(self, governor: RiskGovernor | None = None):
        self.governor = governor or RiskGovernor()

    def formulate_plan(
        self,
        trade_intents: list[TradeIntent],
        allocation_intents: list[AllocationIntent],
        portfolio: PortfolioSnapshot,
        risk_state: RiskState
    ) -> ActionPlan:
        """Merge all intents into a single executable ActionPlan."""
        plan = ActionPlan(rationale="CIO formulation based on incoming intents.")

        # Process allocations
        if allocation_intents:
            # Simple tie-break: latest intent dict update
            for alloc_int in allocation_intents:
                plan.allocation_shifts = {
                    "cash_pct": alloc_int.cash_pct,
                    "baseline_pct": alloc_int.baseline_pct,
                    "swing_pct": alloc_int.swing_pct,
                }

        # Process trade intents
        for intent in trade_intents:
            # 1. Size the intent into an Order
            # Map conviction string matching integer scores (5-8) for sizing
            score_map = {
                "LOW": 5,
                "MEDIUM": 6,
                "HIGH": 7,
                "VERY_HIGH": 8
            }
            score = score_map.get(intent.conviction.value, 5)

            # Requires a current price. Pull from portfolio positions or intent meta.
            # Real execution would fetch real-time mid-price. 
            price = intent.meta.get("latest_price", 100.0)
            atr = intent.meta.get("atr_14", 1.0)

            sizing_result = position_size(
                price=price,
                atr=atr,
                equity=portfolio.equity,
                regime=risk_state.regime,
                score=score
            )

            # Skip size 0
            if sizing_result["qty"] <= 0:
                continue

            order = Order(
                ticker=intent.ticker,
                direction=intent.direction,
                qty=sizing_result["qty"],  # type: ignore
                price=price,
                stop_loss=intent.stop_price,
                take_profit=intent.target_price,
                source_engine=intent.source,
                reason_codes=[r.code for r in intent.reasons]
            )

            # 2. Ask Risk Governor for veto/approval
            order, veto = self.governor.evaluate_order(order, risk_state, portfolio)
            if veto.vetoed:
                order.meta["veto_reason"] = veto.reason

            plan.orders.append(order)

        return plan
