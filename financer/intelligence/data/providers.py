"""Data providers for the intelligence layer.

Wraps yfinance (prices) and FRED (yield curve) with graceful degradation.
Every function accepts an optional ``provider`` callable for test injection
(same pattern as financer.data.prices).

If a fetch fails, functions return ``None`` and log a warning — never crash.
"""

from __future__ import annotations

import logging
from typing import Callable, Optional

import pandas as pd

logger = logging.getLogger(__name__)


# ── Price data ───────────────────────────────────────────────────────────────

def fetch_price_data(
    ticker: str,
    start: str,
    end: str,
    timeframe: str = "1d",
    provider: Callable[..., pd.DataFrame] | None = None,
) -> Optional[pd.DataFrame]:
    """Fetch OHLCV bars for a single ticker.

    Delegates to ``financer.data.prices.get_bars`` by default so that
    caching, normalization, and retry logic are reused.

    Returns ``None`` on any failure (graceful degradation).

    Parameters
    ----------
    ticker : str
        Instrument symbol (e.g. "SPY", "^VIX").
    start, end : str
        Date strings like "2025-01-01".
    timeframe : str
        Bar interval, default "1d".
    provider : callable, optional
        Custom fetch function for tests.  Signature:
        ``(ticker, start, end, interval) -> pd.DataFrame``.
    """
    try:
        from financer.data.prices import get_bars  # noqa: PLC0415

        return get_bars(ticker, start=start, end=end, timeframe=timeframe,
                        provider=provider)
    except Exception:
        logger.warning("Failed to fetch price data for %s", ticker, exc_info=True)
        return None


def fetch_multiple_tickers(
    tickers: list[str],
    start: str,
    end: str,
    timeframe: str = "1d",
    provider: Callable[..., pd.DataFrame] | None = None,
) -> dict[str, pd.DataFrame]:
    """Fetch bars for several tickers, skipping failures.

    Returns a dict of ``{ticker: DataFrame}`` for tickers that succeeded.
    Failed tickers are omitted (logged at WARNING).
    """
    results: dict[str, pd.DataFrame] = {}
    for ticker in tickers:
        df = fetch_price_data(ticker, start=start, end=end,
                              timeframe=timeframe, provider=provider)
        if df is not None and not df.empty:
            results[ticker] = df
    return results


# ── Yield curve (FRED) ───────────────────────────────────────────────────────

def fetch_yield_curve(
    api_key: str | None = None,
    series_id: str = "T10Y2Y",
    lookback_days: int = 30,
    provider: Callable[..., Optional[float]] | None = None,
) -> Optional[float]:
    """Fetch the latest 10Y-2Y yield spread from FRED.

    Returns the most recent spread value as a float, or ``None`` if
    FRED is unavailable or the ``fredapi`` package is not installed.

    Parameters
    ----------
    api_key : str, optional
        FRED API key.  If ``None``, attempts to read from the
        ``FRED_API_KEY`` environment variable.
    series_id : str
        FRED series identifier, default "T10Y2Y".
    lookback_days : int
        How many days of history to request (we only need the latest).
    provider : callable, optional
        Test injection: ``(series_id, lookback_days) -> float | None``.
    """
    if provider is not None:
        try:
            return provider(series_id, lookback_days)
        except Exception:
            logger.warning("Yield curve provider failed", exc_info=True)
            return None

    try:
        import os  # noqa: PLC0415

        from fredapi import Fred  # noqa: PLC0415

        key = api_key or os.environ.get("FRED_API_KEY")
        if not key:
            logger.debug("No FRED_API_KEY; yield curve unavailable")
            return None

        fred = Fred(api_key=key)
        data = fred.get_series_latest_release(series_id)
        if data is None or data.empty:
            return None
        return float(data.dropna().iloc[-1])
    except ImportError:
        logger.debug("fredapi not installed; yield curve unavailable")
        return None
    except Exception:
        logger.warning("FRED fetch failed for %s", series_id, exc_info=True)
        return None
