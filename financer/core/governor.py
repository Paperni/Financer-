"""Risk Governor filtering proposed orders."""

from __future__ import annotations

from financer.models.actions import Order
from financer.models.enums import Direction, OrderStatus
from financer.models.risk import RiskState, RiskVeto


class RiskGovernor:
    """Evaluates orders against portfolio risk limits."""

    def __init__(self, max_open_risk_pct: float = 0.20):
        self.max_open_risk_pct = max_open_risk_pct

    def evaluate_order(self, order: Order, state: RiskState) -> tuple[Order, RiskVeto]:
        """Check an order against current risk parameters.
        
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

        if state.open_risk_pct >= self.max_open_risk_pct:
            checks_failed.append(f"open_risk_pct ({state.open_risk_pct:.2%}) >= max ({self.max_open_risk_pct:.2%})")
        else:
            checks_passed.append("open_risk_limit_ok")

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
