"""Action models — produced exclusively by the CIO Orchestrator.

The CIO merges intents from all engines, resolves conflicts, and emits
an ActionPlan containing concrete Order objects.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field

from .enums import Direction, EngineSource, OrderStatus
from .intents import TradeIntent


class Order(BaseModel):
    """A concrete, sized order ready for risk review and execution."""
    order_id: str = Field(default_factory=lambda: uuid4().hex[:12])
    ticker: str
    direction: Direction
    qty: int
    price: float                        # limit or expected fill price
    stop_loss: float | None = None
    take_profit: float | None = None
    status: OrderStatus = OrderStatus.PROPOSED
    source_engine: EngineSource
    reason_codes: list[str]             # flattened from intent ReasonCodes
    meta: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ActionPlan(BaseModel):
    """A batch of orders and allocation shifts produced by the CIO."""
    plan_id: str = Field(default_factory=lambda: uuid4().hex[:12])
    orders: list[Order] = Field(default_factory=list)
    allocation_shifts: dict[str, float] = Field(default_factory=dict)
    vetoed_intents: list[TradeIntent] = Field(default_factory=list)
    rationale: str = ""
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
