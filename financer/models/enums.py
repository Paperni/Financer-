"""Shared enumerations used across all Financer Brain layers."""

from __future__ import annotations

from enum import Enum


class Direction(str, Enum):
    """Trade direction."""
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"


class TimeHorizon(str, Enum):
    """Expected holding period category."""
    SWING = "SWING"            # days to ~2 weeks
    LONG_TERM = "LONG_TERM"    # months to years


class EngineSource(str, Enum):
    """Which engine produced the intent or order."""
    LONG_TERM = "long_term"
    SWING = "swing"


class Conviction(str, Enum):
    """Signal confidence level."""
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    VERY_HIGH = "VERY_HIGH"


class Regime(str, Enum):
    """Market regime classification."""
    RISK_ON = "RISK_ON"
    CAUTIOUS = "CAUTIOUS"
    RISK_OFF = "RISK_OFF"


class OrderStatus(str, Enum):
    """Lifecycle state of an order."""
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    VETOED = "VETOED"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
