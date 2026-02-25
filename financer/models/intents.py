"""Intent models — the standardized output of every engine.

Engines produce TradeIntent and AllocationIntent objects.
They never create orders directly; only the CIO Orchestrator does that.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field

from .enums import Conviction, Direction, EngineSource, Regime, TimeHorizon


class ReasonCode(BaseModel):
    """A single reason supporting an intent decision."""
    code: str                           # e.g. "STRONG_MOAT", "RSI_OVERSOLD"
    weight: float = 1.0                 # importance 0.0–1.0
    detail: str = ""                    # human-readable explanation


class TradeIntent(BaseModel):
    """An engine's recommendation to buy, sell, or hold a specific ticker."""
    ticker: str
    direction: Direction
    conviction: Conviction
    time_horizon: TimeHorizon
    source: EngineSource
    reasons: list[ReasonCode]
    suggested_weight_pct: float | None = None   # % of engine's allocated capital
    stop_price: float | None = None
    target_price: float | None = None
    meta: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class AllocationIntent(BaseModel):
    """An engine's desired portfolio allocation split."""
    source: EngineSource
    cash_pct: float                     # desired % in cash
    baseline_pct: float                 # desired % in baseline ETF (e.g. QQQ)
    swing_pct: float                    # desired % in active swing positions
    regime: Regime
    reasons: list[ReasonCode]
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
