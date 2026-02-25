"""Position Manager — evaluates bar-by-bar exits for open positions."""

from __future__ import annotations

import pandas as pd
from datetime import datetime

from financer.execution.policy import (
    STOP_LOSS_ATR_MULTIPLIER,
    TRAILING_STOP_ATR_MULTIPLIER,
    TP_TIERS_R,
    TIME_STOP_DAYS,
)
from financer.models.portfolio import PortfolioSnapshot, PositionState
from financer.models.intents import TradeIntent, ReasonCode
from financer.models.enums import Direction, Conviction, TimeHorizon, EngineSource


class PositionManager:
    """Manages active trades, evaluates trailing stops & profit targets."""

    def evaluate_exits(
        self, portfolio: PortfolioSnapshot, latest_features: dict[str, pd.Series], current_date: datetime
    ) -> tuple[list[TradeIntent], dict[str, float]]:
        """Check all positions against execution policy derived limits.
        
        Returns:
            - A list of exit intents (TradeIntent)
            - A dictionary mapping ticker to new updated stop loss (for trailing stops).
              This keeps PositionManager purely functional without mutating the portfolio inline.
        """
        exit_intents = []
        trail_updates = {}
        
        for pos in portfolio.positions:
            if pos.ticker not in latest_features:
                continue
                
            row = latest_features[pos.ticker]
            curr_price = float(row.get("Close", pos.current_price))
            
            # Simple Time Stop
            days_held = (current_date.date() - pos.opened_at.date()).days
            if days_held > TIME_STOP_DAYS:
                exit_intents.append(self._create_exit_intent(pos, curr_price, "TIME_STOP"))
                continue
            
            # Evaluate Trailing Stop
            atr_14 = float(row.get("atr_14", 0.0))
            if atr_14 > 0:
                trail_price = curr_price - (TRAILING_STOP_ATR_MULTIPLIER * atr_14)
                if pos.stop_loss is None or trail_price > pos.stop_loss:
                    trail_updates[pos.ticker] = trail_price  # Suggest new trail stop upwards
            
            # Evaluate Stop Loss
            current_stop_loss = trail_updates.get(pos.ticker, pos.stop_loss)
            if current_stop_loss is not None and curr_price <= current_stop_loss:
                exit_intents.append(self._create_exit_intent(pos, curr_price, "STOP_LOSS"))
                continue
                
            # Evaluate TP Tiers
            if atr_14 > 0:
                risk_1r = STOP_LOSS_ATR_MULTIPLIER * atr_14
                hit_tp = False
                for tier_r in TP_TIERS_R:
                    target_price = pos.entry_price + (tier_r * risk_1r)
                    if curr_price >= target_price:
                        hit_tp = True
                        break
                        
                if hit_tp:
                    exit_intents.append(self._create_exit_intent(pos, curr_price, "TAKE_PROFIT_TIER"))
                    continue
                
        return exit_intents, trail_updates

    def _create_exit_intent(self, pos: PositionState, curr_price: float, reason: str) -> TradeIntent:
        return TradeIntent(
            ticker=pos.ticker,
            direction=Direction.SELL,
            conviction=Conviction.HIGH,
            time_horizon=TimeHorizon.SWING,
            source=EngineSource.SWING,
            reasons=[ReasonCode(code=reason, detail=f"Hit {reason}")],
            meta={"latest_price": curr_price}
        )
