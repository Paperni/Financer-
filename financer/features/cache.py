"""Parquet-based feature cache — cheap persistence for computed features.

Cache layout:
    data/cache/features/{TICKER}_{timeframe}.parquet

If the cached file exists and covers the requested date range,
it is returned directly.  Otherwise the caller recomputes and
calls ``save`` to persist.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

_DEFAULT_CACHE_DIR = Path("data/cache/features")


def _cache_path(ticker: str, timeframe: str, cache_dir: Path) -> Path:
    return cache_dir / f"{ticker}_{timeframe}.parquet"


def load(
    ticker: str,
    timeframe: str,
    start: str,
    end: str,
    cache_dir: Path = _DEFAULT_CACHE_DIR,
) -> pd.DataFrame | None:
    """Return cached features if they cover [start, end], else None."""
    path = _cache_path(ticker, timeframe, cache_dir)
    if not path.exists():
        return None

    try:
        df = pd.read_parquet(path)
    except Exception:
        return None

    if df.empty:
        return None

    # Check coverage
    start_ts = pd.Timestamp(start, tz="UTC")
    end_ts = pd.Timestamp(end, tz="UTC")

    if df.index.min() > start_ts or df.index.max() < end_ts:
        return None

    # Slice to requested range
    return df.loc[start_ts:end_ts]


def save(
    df: pd.DataFrame,
    ticker: str,
    timeframe: str,
    cache_dir: Path = _DEFAULT_CACHE_DIR,
) -> Path:
    """Persist a features DataFrame to parquet.  Returns the file path."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = _cache_path(ticker, timeframe, cache_dir)
    df.to_parquet(path, engine="pyarrow")
    return path
