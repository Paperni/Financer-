"""Risk Governor filtering proposed orders."""

from __future__ import annotations

from financer.models.actions import Order
from financer.models.enums import Direction, OrderStatus
from financer.models.intents import TradeIntent
from financer.models.risk import RiskState, RiskVeto
from financer.models.portfolio import PortfolioSnapshot


class RiskGovernor:
    """Evaluates orders against portfolio risk limits."""

    def __init__(self, max_open_risk_pct: float = 0.20):
        self.max_open_risk_pct = max_open_risk_pct

    def veto_intents(
        self, intents: list[TradeIntent], portfolio: PortfolioSnapshot
    ) -> tuple[list[TradeIntent], list[TradeIntent]]:
        """Filter intents prior to order sizing (e.g. anti-pyramiding)."""
        approved = []
        vetoed = []

        # Tethers
        held_tickers = {p.ticker for p in portfolio.positions}

        for intent in intents:
            if intent.direction == Direction.BUY and intent.ticker in held_tickers:
                intent.meta["veto_reason"] = f"ticker_already_held: {intent.ticker} (anti-pyramiding)"
                vetoed.append(intent)
            else:
                approved.append(intent)

        return approved, vetoed

    def evaluate_order(
        self, order: Order, state: RiskState, portfolio: PortfolioSnapshot | None = None
    ) -> tuple[Order, RiskVeto]:
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

        # 1. Anti-pyramiding
        if portfolio is not None:
            existing = [p for p in portfolio.positions if p.ticker == order.ticker]
            if existing:
                checks_failed.append(f"ticker_already_held: {order.ticker} (anti-pyramiding)")
            else:
                checks_passed.append("anti_pyramiding_ok")

        # 2. Max Open Risk
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
