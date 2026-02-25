"""Price bar adapter — the single source of normalized OHLCV data.

Default provider fetches from yfinance.  Pass a custom ``provider``
callable for tests or alternative data sources.
"""

from __future__ import annotations

from typing import Any, Callable

import pandas as pd


# ── Column schema every consumer can rely on ────────────────────────────────
EXPECTED_COLUMNS: list[str] = ["open", "high", "low", "close", "volume"]
INDEX_NAME: str = "timestamp"


def _empty_bars() -> pd.DataFrame:
    """Return an empty DataFrame with the canonical schema."""
    df = pd.DataFrame(columns=EXPECTED_COLUMNS)
    df.index = pd.DatetimeIndex([], name=INDEX_NAME, tz="UTC")
    return df


def _default_provider(ticker: str, start: str, end: str, interval: str) -> pd.DataFrame:
    """Fetch bars from yfinance.  Imported lazily to keep tests fast."""
    import yfinance as yf  # noqa: PLC0415

    df = yf.download(ticker, start=start, end=end, interval=interval, progress=False)
    if df is None or df.empty:
        return pd.DataFrame()
    return df


def _normalize(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize a raw provider DataFrame to canonical schema."""
    if df.empty:
        return _empty_bars()

    # yfinance may return MultiIndex columns for single tickers — flatten
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    # Lowercase column names
    df.columns = [c.lower().strip() for c in df.columns]

    # Keep only expected columns that exist
    present = [c for c in EXPECTED_COLUMNS if c in df.columns]
    if not present:
        return _empty_bars()
    df = df[present].copy()

    # Add any missing expected columns as NaN
    for c in EXPECTED_COLUMNS:
        if c not in df.columns:
            df[c] = float("nan")

    # Drop rows where all OHLC values are NaN
    ohlc = ["open", "high", "low", "close"]
    df = df.dropna(subset=ohlc, how="all")

    # Ensure DatetimeIndex
    if not isinstance(df.index, pd.DatetimeIndex):
        df.index = pd.to_datetime(df.index)

    # Timezone: localize naive to UTC, convert aware to UTC
    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC")
    else:
        df.index = df.index.tz_convert("UTC")

    df.index.name = INDEX_NAME

    # Remove duplicate timestamps, keep last
    df = df[~df.index.duplicated(keep="last")]

    # Sort ascending
    df = df.sort_index()

    return df


def get_bars(
    ticker: str,
    start: str,
    end: str,
    timeframe: str = "1d",
    provider: Callable[..., pd.DataFrame] | None = None,
) -> pd.DataFrame:
    """Fetch and normalize OHLCV bars for a single ticker.

    Parameters
    ----------
    ticker : str
        Instrument symbol (e.g. "AAPL").
    start, end : str
        Date strings like "2025-11-01".
    timeframe : str
        Bar interval — "1d", "1h", "5m", etc.
    provider : callable, optional
        ``provider(ticker, start, end, interval) -> DataFrame``.
        Defaults to yfinance.

    Returns
    -------
    pd.DataFrame
        Columns: open, high, low, close, volume.
        Index: DatetimeIndex named ``timestamp``, tz-aware UTC.
    """
    fetch = provider or _default_provider
    try:
        raw = fetch(ticker, start, end, timeframe)
    except Exception:
        return _empty_bars()
    return _normalize(raw)


def get_market_bars(
    market_ticker: str = "SPY",
    start: str = "",
    end: str = "",
    timeframe: str = "1d",
    provider: Callable[..., pd.DataFrame] | None = None,
) -> pd.DataFrame:
    """Convenience wrapper: fetch bars for a market index ticker."""
    return get_bars(market_ticker, start=start, end=end, timeframe=timeframe, provider=provider)
