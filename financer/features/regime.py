"""Market-regime classification from SPY SMA structure.

Matches the existing indicators.py logic:
  RISK_ON  — SPY > SMA-50 AND SMA-200
  CAUTIOUS — SPY > SMA-200 but < SMA-50
  RISK_OFF — SPY < SMA-200
"""

from __future__ import annotations

import pandas as pd

from financer.models.enums import Regime


def classify_regime(market_df: pd.DataFrame) -> pd.Series:
    """Return a Series of Regime enum values aligned to *market_df* index.

    Parameters
    ----------
    market_df : pd.DataFrame
        Market bars (e.g. SPY) with ``close`` column. Must already have
        ``sma_50`` and ``sma_200`` columns (call ``add_sma`` first).

    Returns
    -------
    pd.Series
        Regime labels indexed to *market_df*.
    """
    close = market_df["close"]
    sma50 = market_df.get("sma_50")
    sma200 = market_df.get("sma_200")

    if sma50 is None or sma200 is None:
        return pd.Series(Regime.RISK_ON, index=market_df.index, dtype=object)

    regime = pd.Series(Regime.RISK_ON, index=market_df.index, dtype=object)

    # RISK_OFF: close < SMA-200
    risk_off_mask = close < sma200
    regime[risk_off_mask] = Regime.RISK_OFF

    # CAUTIOUS: close > SMA-200 but < SMA-50
    cautious_mask = (close >= sma200) & (close < sma50)
    regime[cautious_mask] = Regime.CAUTIOUS

    # RISK_ON: close >= SMA-50 (and implicitly >= SMA-200)
    # Already the default

    return regime
