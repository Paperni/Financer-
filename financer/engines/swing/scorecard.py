"""Scorecard for the Swing Engine to evaluate a bar of features into conviction scores."""

from __future__ import annotations

import pandas as pd

from financer.models.intents import ReasonCode

RSI_BAND_LOWER = 30
RSI_BAND_UPPER = 45


def score_setup(row: pd.Series) -> tuple[int, list[ReasonCode]]:
    """Score a potential entry from 0-8 based on institutional-style confirmations.

    Uses properties from `financer.features.build_features` output.
    """
    score = 0
    reasons = []

    try:
        # 1. Uptrend (Price above 50 SMA)
        above_50 = bool(row.get("above_50", False))
        if above_50:
            score += 1
            reasons.append(ReasonCode(code="TREND_UP", weight=1.0, detail="Price is above 50-period SMA."))

        # 2. RSI Pullback zone
        rsi = float(row.get("rsi_14", 50.0))
        if not pd.isna(rsi):
            if RSI_BAND_LOWER <= rsi <= RSI_BAND_UPPER:
                score += 1
                reasons.append(ReasonCode(code="RSI_PULLBACK", weight=1.0, detail=f"RSI {rsi:.1f} is in the sweet spot."))
            elif 25 <= rsi < 30:
                score += 0.5
                reasons.append(ReasonCode(code="RSI_OVERSOLD", weight=0.5, detail=f"RSI {rsi:.1f} is deeply oversold."))

        # 3. MACD Momentum
        macd_hist = float(row.get("macd_hist", 0.0))
        if not pd.isna(macd_hist) and macd_hist > 0:
            score += 1
            reasons.append(ReasonCode(code="MACD_POSITIVE", weight=1.0, detail="MACD histogram is positive."))

        # 4. Relative Strength vs SPY
        rs_20 = float(row.get("rs_20", 0.0))
        if not pd.isna(rs_20):
            if rs_20 > 1.05:
                score += 1
                reasons.append(ReasonCode(code="STRONG_RS", weight=1.0, detail=f"RS {rs_20:.2f} shows strong outperformance."))
            elif rs_20 > 1.0:
                score += 0.5
                reasons.append(ReasonCode(code="POSITIVE_RS", weight=0.5, detail="RS shows mild outperformance."))

        # 5. Valuation (PEG Proxy)
        peg = float(row.get("peg_proxy", 2.0))
        if not pd.isna(peg) and peg <= 1.2:
            score += 1
            reasons.append(ReasonCode(code="FAIR_VALUATION", weight=1.0, detail=f"PEG {peg:.2f} indicates fair valuation."))

        # 6. Event Risk Free
        earnings_7d = bool(row.get("earnings_within_7d", True))
        if not earnings_7d:
            score += 1
            reasons.append(ReasonCode(code="NO_EARNINGS_RISK", weight=1.0, detail="No earnings expected within next 7 days."))

        # (Leaving room for volume scoring out of 8 later, maxing at 6 points here based on limited standard features)

    except (KeyError, TypeError, ValueError):
        pass

    return score, reasons
