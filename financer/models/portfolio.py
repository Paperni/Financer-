"""Portfolio state models — position tracking and snapshots."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field

from .enums import EngineSource


class PositionState(BaseModel):
    """Current state of a single position."""
    ticker: str
    qty: int
    entry_price: float
    current_price: float = 0.0
    stop_loss: float | None = None
    take_profit_1: float | None = None
    take_profit_2: float | None = None
    take_profit_3: float | None = None
    atr_at_entry: float | None = None
    source: EngineSource
    opened_at: datetime
    is_baseline: bool = False
    meta: dict[str, Any] = Field(default_factory=dict)

    @property
    def unrealized_pnl(self) -> float:
        return (self.current_price - self.entry_price) * self.qty

    @property
    def market_value(self) -> float:
        return self.current_price * self.qty


class PortfolioSnapshot(BaseModel):
    """Point-in-time view of the full portfolio."""
    cash: float
    positions: list[PositionState]
    initial_capital: float = 100_000.0
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def equity(self) -> float:
        return self.cash + sum(p.market_value for p in self.positions)

    @property
    def drawdown_pct(self) -> float:
        if self.initial_capital <= 0:
            return 0.0
        return max(0.0, 1.0 - self.equity / self.initial_capital)
