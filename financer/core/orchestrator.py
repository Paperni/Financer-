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

    def __init__(
        self,
        governor: RiskGovernor | None = None,
        cautious_size_mult: float = 0.75,
        risk_per_trade_pct: float | None = None
    ):
        self.governor = governor or RiskGovernor()
        self.cautious_size_mult = cautious_size_mult
        self.risk_per_trade_pct = risk_per_trade_pct

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
                }

        # Veto intents before execution (e.g. anti-pyramiding)
        approved_trade_intents, vetoed_intents = self.governor.veto_intents(trade_intents, portfolio)
        plan.vetoed_intents.extend(vetoed_intents)

        # Process trade intents
        for intent in approved_trade_intents:
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
                score=score,
                risk_per_trade_pct=self.risk_per_trade_pct
            )

            qty = sizing_result["qty"]
            
            # Skip size 0
            if qty <= 0:
                continue
                
            # Reduce risk by half for Pyramiding bullets
            if intent.meta.get("is_pyramid_add", False):
                qty = max(1, int(qty * 0.5))
                
            # Apply class cautious multiplier if strictly in cautious mode
            if risk_state.regime.value == "CAUTIOUS" and not getattr(sizing_result, "_cautious_applied", False):
                # Models check global multiplier. We override if desired.
                pass

            order = Order(
                ticker=intent.ticker,
                direction=intent.direction,
                qty=qty,  # type: ignore
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
