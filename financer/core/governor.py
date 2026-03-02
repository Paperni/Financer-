"""Risk Governor filtering proposed orders."""

from __future__ import annotations

from financer.models.actions import Order
from financer.models.enums import Direction, OrderStatus
from financer.models.intents import TradeIntent
from financer.models.risk import RiskState, RiskVeto
from financer.models.portfolio import PortfolioSnapshot


class RiskGovernor:
    """Evaluates orders against portfolio risk limits."""

    def __init__(
        self,
        max_open_risk_pct: float = 0.20,
        max_positions: int = 20,
        max_heat_R: float = 5.0,
        pyramiding_mode: str = "off"
    ):
        self.max_open_risk_pct = max_open_risk_pct
        self.max_positions = max_positions
        self.max_heat_R = max_heat_R
        self.pyramiding_mode = pyramiding_mode

    def veto_intents(
        self, intents: list[TradeIntent], portfolio: PortfolioSnapshot
    ) -> tuple[list[TradeIntent], list[TradeIntent]]:
        """Filter intents prior to order sizing (e.g. anti-pyramiding)."""
        approved = []
        vetoed = []

        # Map active positions by ticker for Pyramiding checks
        ticker_positions = {}
        for p in portfolio.positions:
            ticker_positions.setdefault(p.ticker, []).append(p)

        for intent in intents:
            if intent.direction == Direction.BUY and intent.ticker in ticker_positions:
                existing_list = ticker_positions[intent.ticker]
                
                if self.pyramiding_mode == "off":
                    intent.meta["veto_reason"] = f"ticker_already_held: {intent.ticker} (anti-pyramiding)"
                    vetoed.append(intent)
                    continue
                
                # Pyramiding is "on"
                # Rule 1: Add once only (max 2 bullets total per ticker)
                if len(existing_list) >= 2:
                    intent.meta["veto_reason"] = f"max_pyramid_bullets_reached_for_{intent.ticker}"
                    vetoed.append(intent)
                    continue
                    
                # Rule 2: Must be +1R in profit to add
                pos = existing_list[0]
                if pos.stop_loss is None or pos.stop_loss >= pos.entry_price:
                    intent.meta["veto_reason"] = f"no_valid_stop_to_calculate_R_for_{intent.ticker}"
                    vetoed.append(intent)
                    continue
                    
                r_dist = pos.entry_price - pos.stop_loss
                if (pos.current_price - pos.entry_price) < r_dist:
                    intent.meta["veto_reason"] = f"not_at_plus_1R_yet_for_{intent.ticker}"
                    vetoed.append(intent)
                    continue
                    
                # Passed pyramiding rules, tag intent so orchestrator half-sizes it
                intent.meta["is_pyramid_add"] = True
                approved.append(intent)
            else:
                approved.append(intent)

        return approved, vetoed

    def evaluate_order(
        self, order: Order, state: RiskState, portfolio: PortfolioSnapshot | None = None,
        control_plan: object | None = None,
    ) -> tuple[Order, RiskVeto]:
        """Check an order against current risk parameters.

        If *control_plan* is provided, its ``max_positions`` overrides the
        governor's static limit for this evaluation only.
        If vetoed, the Order status is mutated to VETOED.
        """
        # Exits are always allowed
        if order.direction == Direction.SELL:
            order.status = OrderStatus.APPROVED
            return order, RiskVeto(
                order_id=order.order_id,
                vetoed=False,
                checks_passed=["direction_sell_allowed"]
            )

        # Global halt check
        if state.halt_active:
            order.status = OrderStatus.VETOED
            return order, RiskVeto(
                order_id=order.order_id,
                vetoed=True,
                reason=f"Global trading halt: {state.halt_reason}"
            )

        # Risk limits for new entries
        checks_passed = []
        checks_failed = []

        # 1. Max Positions (ControlPlan can only restrict, never expand)
        effective_max = self.max_positions
        if control_plan is not None and hasattr(control_plan, "max_positions"):
            effective_max = min(self.max_positions, control_plan.max_positions)
        current_pos_count = len(portfolio.positions) if portfolio else 0
        if current_pos_count >= effective_max:
            checks_failed.append(f"max_positions_reached: {current_pos_count} >= {effective_max}")
        else:
            checks_passed.append("max_positions_ok")

        # 2. Max Open Risk & Heat R
        # open_risk_pct remains as a hard baseline limit (typically 20-30%)
        if state.open_risk_pct >= self.max_open_risk_pct:
            checks_failed.append(f"open_risk_pct ({state.open_risk_pct:.2%}) >= max ({self.max_open_risk_pct:.2%})")
        else:
            checks_passed.append("open_risk_limit_ok")
            
        # Calculate Heat R dynamically if a new order lands
        if portfolio is not None and portfolio.equity > 0:
            open_risk_dollars = sum((p.current_price - (p.stop_loss or 0.0)) * p.qty for p in portfolio.positions if p.stop_loss)
            
            # Predict the new addition to Heat R
            order_risk_dollars = 0.0
            if order.stop_loss is not None and order.price > order.stop_loss:
                order_risk_dollars = (order.price - order.stop_loss) * order.qty
                
            total_proposed_risk_dollars = open_risk_dollars + order_risk_dollars
            
            # We assume a base 1R is 1% of equity for calculating total R-heat globally
            base_1r_dollars = portfolio.equity * 0.01 
            proposed_heat_R = total_proposed_risk_dollars / base_1r_dollars if base_1r_dollars > 0 else 0
            
            if proposed_heat_R > self.max_heat_R:
                checks_failed.append(f"max_heat_R_exceeded: proposed {proposed_heat_R:.2f}R > {self.max_heat_R}R")
            else:
                checks_passed.append("max_heat_R_ok")

        is_vetoed = len(checks_failed) > 0
        order.status = OrderStatus.VETOED if is_vetoed else OrderStatus.APPROVED

        veto = RiskVeto(
            order_id=order.order_id,
            vetoed=is_vetoed,
            reason="; ".join(checks_failed) if is_vetoed else "OK",
            checks_passed=checks_passed,
            checks_failed=checks_failed
        )

        return order, veto
