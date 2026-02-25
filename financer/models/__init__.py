"""Financer Brain core models — re-exports for convenient importing.

Usage:
    from financer.models import TradeIntent, ActionPlan, PositionState
"""

from .actions import ActionPlan, Order
from .enums import (
    Conviction,
    Direction,
    EngineSource,
    OrderStatus,
    Regime,
    TimeHorizon,
)
from .events import EventFlags
from .intents import AllocationIntent, ReasonCode, TradeIntent
from .portfolio import PortfolioSnapshot, PositionState
from .risk import RiskState, RiskVeto, check_regime_allows_entry
from .sizing import check_entry_readiness, position_size

__all__ = [
    # Enums
    "Conviction",
    "Direction",
    "EngineSource",
    "OrderStatus",
    "Regime",
    "TimeHorizon",
    # Intents (engine output)
    "ReasonCode",
    "TradeIntent",
    "AllocationIntent",
    # Actions (CIO output)
    "Order",
    "ActionPlan",
    # Portfolio state
    "PositionState",
    "PortfolioSnapshot",
    # Risk
    "RiskState",
    "RiskVeto",
    # Events
    "EventFlags",
    # Functions
    "position_size",
    "check_entry_readiness",
    "check_regime_allows_entry",
]
