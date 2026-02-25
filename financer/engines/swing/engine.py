"""The Core Swing Engine.

Drafts assets, scores them, and emits TradeIntents.
"""

from __future__ import annotations

import pandas as pd

from financer.models.enums import Conviction, Direction, EngineSource, TimeHorizon
from financer.models.intents import TradeIntent

from .draft import draft_assets
from .scorecard import score_setup


class SwingEngine:
    """The Swing Engine evaluates features to emit TradeIntents."""

    def __init__(self, min_entry_score: float = 4.0, max_draft: int = 10):
        self.min_entry_score = min_entry_score
        self.max_draft = max_draft

    def evaluate(self, latest_features: dict[str, pd.Series]) -> list[TradeIntent]:
        """Evaluate the latest features for all universe tickers and emit intents."""
        intents = []

        # 1. Draft the best momentum assets
        drafted_tickers = draft_assets(latest_features, n_select=self.max_draft)

        # 2. Score setups
        for ticker in drafted_tickers:
            row = latest_features[ticker]
            score, reasons = score_setup(row)

            if score >= self.min_entry_score:
                # Calculate Conviction based on score
                if score >= 6.0:
                    conviction = Conviction.VERY_HIGH
                elif score >= 5.0:
                    conviction = Conviction.HIGH
                elif score >= 4.0:
                    conviction = Conviction.MEDIUM
                else:
                    conviction = Conviction.LOW

                atr_14 = float(row.get("atr_14", 0.0))
                close_price = float(row.get("Close", 100.0))  # Provided by data bars, default 100

                stop_price = close_price - (1.5 * atr_14) if atr_14 > 0 else None
                target_price = close_price + (4.0 * atr_14) if atr_14 > 0 else None

                intent = TradeIntent(
                    ticker=ticker,
                    direction=Direction.BUY,
                    conviction=conviction,
                    time_horizon=TimeHorizon.SWING,
                    source=EngineSource.SWING,
                    reasons=reasons,
                    stop_price=stop_price,
                    target_price=target_price,
                )
                intents.append(intent)

        return intents
