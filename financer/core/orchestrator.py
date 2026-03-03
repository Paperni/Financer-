"""CIO Orchestrator — the central brain that routes intents to actions."""

from __future__ import annotations

from financer.models.actions import ActionPlan, Order
from financer.models.enums import Direction
from financer.models.intents import AllocationIntent, TradeIntent
from financer.models.portfolio import PortfolioSnapshot
from financer.models.risk import RiskState
from financer.models.sizing import position_size, VolatilityTargetingSizer

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
        self.sizer = VolatilityTargetingSizer()

    def formulate_plan(
        self,
        trade_intents: list[TradeIntent],
        allocation_intents: list[AllocationIntent],
        portfolio: PortfolioSnapshot,
        risk_state: RiskState,
        control_plan: object | None = None,
        historical_returns: dict | None = None,
    ) -> ActionPlan:
        """Merge all intents into a single executable ActionPlan."""
        historical_returns = historical_returns or {}
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

        # Process trade intents sizing first
        for intent in approved_trade_intents:
            if intent.direction == Direction.BUY:
                asset_vol = intent.meta.get("annualized_vol", 0.15)
                proposed_weight = self.sizer.calculate_weight(asset_vol)
                intent.meta["proposed_weight"] = proposed_weight
                
                price = intent.meta.get("latest_price", 100.0)
                qty = self.sizer.calculate_qty(price, portfolio.equity, asset_vol)
                
                # Apply ControlPlan position_size_multiplier to entries only
                if control_plan is not None and hasattr(control_plan, "position_size_multiplier"):
                    qty = max(0, int(qty * control_plan.position_size_multiplier))
                
                intent.meta["proposed_qty"] = qty
            else:
                intent.meta["proposed_qty"] = intent.meta.get("exit_qty", 0)

        # Batch evaluation for Portfolio CVaR limit
        if hasattr(self.governor, "evaluate_intent_batch"):
            approved_trade_intents, cvar_vetoed = self.governor.evaluate_intent_batch(
                approved_trade_intents, portfolio, historical_returns
            )
            plan.vetoed_intents.extend(cvar_vetoed)

        for intent in approved_trade_intents:
            qty = intent.meta.get("proposed_qty", 0)
            if qty <= 0:
                continue
                
            price = intent.meta.get("latest_price", 100.0)

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
            order, veto = self.governor.evaluate_order(order, risk_state, portfolio, control_plan=control_plan)
            if veto.vetoed:
                order.meta["veto_reason"] = veto.reason

            plan.orders.append(order)

        return plan
