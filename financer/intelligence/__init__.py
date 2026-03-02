"""Market Intelligence Engine — read-only overlay for regime-aware trading.

Produces a ControlPlan consumed by the orchestrator and risk governor.
Does NOT mutate global state or directly open/close trades.

Usage:
    from financer.intelligence import MarketIntelligenceEngine, ControlPlan
"""

from .models import ControlPlan

__all__ = [
    "ControlPlan",
]
