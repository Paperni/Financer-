"""Relative-strength features — ticker performance vs market benchmark.

Computes rolling return ratios over 20 and 60 bars.
RS > 1.0 means the ticker is outperforming the benchmark.
"""

from __future__ import annotations

import pandas as pd


def add_relative_strength(
    df: pd.DataFrame,
    market_df: pd.DataFrame,
    periods: tuple[int, ...] = (20, 60),
) -> pd.DataFrame:
    """Add ``rs_{period}`` columns by comparing ticker returns to market.

    Parameters
    ----------
    df : pd.DataFrame
        Ticker bars with a ``close`` column and UTC DatetimeIndex.
    market_df : pd.DataFrame
        Market (e.g. SPY) bars with a ``close`` column and UTC DatetimeIndex.
    periods : tuple[int, ...]
        Lookback windows in bars (default 20 and 60).

    Returns
    -------
    pd.DataFrame
        Input *df* with ``rs_20``, ``rs_60`` (etc.) columns added.
    """
    # Align market close to ticker index (forward-fill for missing bars)
    market_close = (
        market_df["close"]
        .reindex(df.index, method="ffill")
    )

    for p in periods:
        ticker_ret = df["close"].pct_change(p)
        market_ret = market_close.pct_change(p)
        # RS = (1 + ticker_return) / (1 + market_return)
        df[f"rs_{p}"] = (1 + ticker_ret) / (1 + market_ret)

    return df
