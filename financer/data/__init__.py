"""Financer data layer — unified adapters for prices, fundamentals, events.

Usage:
    from financer.data import get_bars, get_valuation_inputs, filter_universe
"""

from .events import get_earnings_dates, get_event_flags
from .fundamentals import get_valuation_inputs
from .prices import get_bars, get_market_bars
from .universe import filter_universe

__all__ = [
    "get_bars",
    "get_market_bars",
    "get_valuation_inputs",
    "get_earnings_dates",
    "get_event_flags",
    "filter_universe",
]
