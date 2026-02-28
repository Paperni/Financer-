"""Simulated execution broker for backtesting ActionPlans."""

from __future__ import annotations

from datetime import datetime, timezone

from financer.models.actions import ActionPlan
from financer.models.enums import Direction, OrderStatus
from financer.models.portfolio import PortfolioSnapshot, PositionState


class SimBroker:
    """Executes an ActionPlan against a mock portfolio."""

    def execute_plan(
        self,
        plan: ActionPlan,
        portfolio: PortfolioSnapshot,
        current_date: datetime | None = None
    ) -> PortfolioSnapshot:
        """Apply APPROVED orders from the plan to the portfolio."""

        for order in plan.orders:
            if order.status != OrderStatus.APPROVED:
                continue

            if order.direction == Direction.BUY:
                cost = order.qty * order.price
                if portfolio.cash >= cost:
                    # Execute BUY
                    portfolio.cash -= cost
                    now = current_date if current_date is not None else datetime.now(timezone.utc)
                    new_pos = PositionState(
                        ticker=order.ticker,
                        qty=order.qty,
                        entry_price=order.price,
                        current_price=order.price,
                        stop_loss=order.stop_loss,
                        take_profit_1=order.take_profit,
                        source=order.source_engine,
                        opened_at=now
                    )
                    portfolio.positions.append(new_pos)
                    order.status = OrderStatus.FILLED
                else:
                    order.status = OrderStatus.VETOED
                    order.meta["veto_reason"] = "Insufficient cash"

            elif order.direction == Direction.SELL:
                # Find matching position
                matching = [p for p in portfolio.positions if p.ticker == order.ticker]
                if matching:
                    pos = matching[0]
                    # Execute full SELL
                    proceeds = pos.qty * order.price
                    portfolio.cash += proceeds
                    portfolio.positions.remove(pos)
                    order.status = OrderStatus.FILLED
                else:
                    order.status = OrderStatus.VETOED
                    order.meta["veto_reason"] = "Position not found for sell"

        return portfolio
