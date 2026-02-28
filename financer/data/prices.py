"""Price bar adapter — the single source of normalized OHLCV data.

Default provider fetches from yfinance.  Pass a custom ``provider``
callable for tests or alternative data sources.
"""

from __future__ import annotations

from typing import Any, Callable
import time
import os
from pathlib import Path

import pandas as pd

class DataFetchError(Exception):
    """Raised when data fetching fails after retries, or data is malformed."""
    pass


# ── Column schema every consumer can rely on ────────────────────────────────
EXPECTED_COLUMNS: list[str] = ["open", "high", "low", "close", "volume"]
INDEX_NAME: str = "timestamp"


def _empty_bars() -> pd.DataFrame:
    """Return an empty DataFrame with the canonical schema."""
    df = pd.DataFrame(columns=EXPECTED_COLUMNS)
    df.index = pd.DatetimeIndex([], name=INDEX_NAME, tz="UTC")
    return df


def _default_provider(ticker: str, start: str, end: str, interval: str) -> pd.DataFrame:
    """Fetch bars from yfinance with 3x retry and exponential backoff."""
    import yfinance as yf  # noqa: PLC0415

    max_retries = 3
    base_delay = 2.0
    
    for attempt in range(max_retries):
        try:
            df = yf.download(ticker, start=start, end=end, interval=interval, progress=False)
            if df is None or df.empty:
                raise DataFetchError(f"yfinance returned empty data for {ticker}")
            return df
        except Exception as e:
            if attempt == max_retries - 1:
                raise DataFetchError(f"Failed to fetch {ticker} after {max_retries} attempts. Last error: {str(e)}")
            time.sleep(base_delay * (2 ** attempt))
            
    return pd.DataFrame()


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
    """Fetch and normalize OHLCV bars for a single ticker with caching."""
    # 1. Check Cache First
    cache_dir = Path("artifacts/data_cache")
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path = cache_dir / f"{ticker}_{timeframe}_{start}_{end}.parquet"
    
    if cache_path.exists():
        try:
            return pd.read_parquet(cache_path)
        except Exception:
            pass # Fallback to fetch if cache is corrupted
            
    # 2. Fetch Data
    fetch = provider or _default_provider
    try:
        raw = fetch(ticker, start, end, timeframe)
    except DataFetchError:
        raise
    except Exception as e:
        raise DataFetchError(f"Unexpected error fetching {ticker}: {str(e)}")
        
    df = _normalize(raw)
    
    # 3. Save to Cache Output
    if not df.empty:
        df.to_parquet(cache_path)
        
    return df


def get_market_bars(
    market_ticker: str = "SPY",
    start: str = "",
    end: str = "",
    timeframe: str = "1d",
    provider: Callable[..., pd.DataFrame] | None = None,
) -> pd.DataFrame:
    """Convenience wrapper: fetch bars for a market index ticker."""
    return get_bars(market_ticker, start=start, end=end, timeframe=timeframe, provider=provider)
