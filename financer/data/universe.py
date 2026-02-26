"""Universe filter — liquidity and price screening.

Duplicates a subset of tickers from the root-level ``data_static.py``
to respect the import boundary.  Will consolidate when root scripts
migrate into ``financer/``.
"""

from __future__ import annotations

from typing import Callable

import pandas as pd

from .prices import get_bars

# ── Default universe (strategic duplication from data_static.py) ────────────
DEFAULT_STOCKS: list[str] = [
    "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "AVGO",
    "JPM", "V", "UNH", "XOM", "MA", "JNJ", "HD", "PG", "COST", "ABBV",
    "CRM", "LLY", "MRK", "AMD", "NFLX", "ADBE", "PEP", "TMO", "CSCO",
    "QCOM", "INTC", "INTU", "TXN", "ISRG", "AMAT", "BKNG", "PANW",
    "LRCX", "KLAC", "SNPS", "CDNS", "MRVL", "FTNT", "CRWD", "NOW",
    "WDAY", "ZS", "DDOG", "TEAM", "HUBS", "MDB", "NET",
]

DEFAULT_ETFS: list[str] = [
    "SPY", "QQQ", "DIA", "IWM", "VTI", "VOO",
    "XLK", "XLF", "XLV", "XLE", "XLI", "XLY",
    "TLT", "GLD", "SLV",
]

# Minimum thresholds
MIN_PRICE_DEFAULT: float = 10.0
MIN_AVG_DOLLAR_VOLUME_DEFAULT: float = 5_000_000.0  # $5 million
MIN_BARS_REQUIRED: int = 10


def filter_universe(
    tickers: list[str],
    bars_provider: Callable[..., pd.DataFrame] | None = None,
    min_price: float = MIN_PRICE_DEFAULT,
    min_avg_dollar_volume: float = MIN_AVG_DOLLAR_VOLUME_DEFAULT,
    lookback_days: int = 20,
) -> list[str]:
    """Screen tickers by price and dollar-volume liquidity.

    Parameters
    ----------
    tickers : list[str]
        Candidate ticker symbols.
    bars_provider : callable, optional
        ``provider(ticker, start, end, interval) -> DataFrame``.
        Passed through to ``get_bars()`` for testability.
    min_price : float
        Minimum last closing price.
    min_avg_dollar_volume : float
        Minimum average daily dollar volume over ``lookback_days``.
    lookback_days : int
        Number of calendar days to look back for volume averaging.

    Returns
    -------
    list[str]
        Sorted list of tickers that pass all screens.
    """
    from datetime import datetime, timedelta, timezone  # noqa: PLC0415

    end_dt = datetime.now(timezone.utc)
    # Add buffer for weekends/holidays
    start_dt = end_dt - timedelta(days=lookback_days + 10)
    start_str = start_dt.strftime("%Y-%m-%d")
    end_str = end_dt.strftime("%Y-%m-%d")

    passed: list[str] = []

    for ticker in tickers:
        try:
            df = get_bars(ticker, start=start_str, end=end_str, provider=bars_provider)
        except Exception:
            continue

        if len(df) < MIN_BARS_REQUIRED:
            continue

        last_close = float(df["close"].iloc[-1])
        if last_close < min_price:
            continue

        avg_dollar_vol = float((df["close"] * df["volume"]).mean())
        if avg_dollar_vol < min_avg_dollar_volume:
            continue

        passed.append(ticker)

    return sorted(passed)
