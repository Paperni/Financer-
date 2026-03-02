"""Breadth proxy — fraction of universe trading above SMA-200.

Computes daily breadth from pre-loaded feature DataFrames without any
network calls.  Designed to plug into the RiskScore composite as the
breadth sub-score (20% weight).

Definition:
    breadth_pct = 100 * count(close > sma_200) / count(valid close & sma_200)
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)

_CACHE_DIR = Path("artifacts/cache")


def compute_breadth_pct(
    date: pd.Timestamp | str,
    universe: list[str],
    features_map: dict[str, pd.DataFrame],
) -> float:
    """Compute breadth percentage as-of *date*.

    Parameters
    ----------
    date : pd.Timestamp or str
        Observation date.  Only data up to and including this date is used.
    universe : list[str]
        Ticker symbols to include in the breadth calculation.
    features_map : dict[str, pd.DataFrame]
        ``{ticker: DataFrame}`` with DatetimeIndex and columns
        ``close``, ``sma_200``.

    Returns
    -------
    float
        Percentage of universe above SMA-200 (0.0–100.0).
        Returns 50.0 if no valid observations.
    """
    dt = pd.Timestamp(date)
    if dt.tzinfo is None:
        dt = dt.tz_localize("UTC")

    valid = 0
    above = 0

    for ticker in universe:
        df = features_map.get(ticker)
        if df is None or df.empty:
            continue

        if "close" not in df.columns or "sma_200" not in df.columns:
            continue

        sliced = df.loc[:dt]
        if sliced.empty:
            continue

        row = sliced.iloc[-1]
        close = row["close"]
        sma200 = row["sma_200"]

        if pd.isna(close) or pd.isna(sma200):
            continue

        valid += 1
        if close > sma200:
            above += 1

    if valid == 0:
        return 50.0

    return 100.0 * above / valid


def _breadth_cache_key(universe: list[str], start: str, end: str) -> str:
    """Build a deterministic cache key from universe + date range."""
    raw = "|".join(sorted(universe)) + f"|{start}|{end}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def compute_breadth_series(
    start: str,
    end: str,
    universe: list[str],
    features_map: dict[str, pd.DataFrame],
    cache_dir: Path | str | None = None,
) -> pd.Series:
    """Compute daily breadth percentage over a date range.

    Parameters
    ----------
    start, end : str
        Date range strings like "2021-01-01".
    universe : list[str]
        Ticker symbols.
    features_map : dict[str, pd.DataFrame]
        Pre-loaded feature DataFrames.
    cache_dir : Path, optional
        Override cache directory.  Defaults to ``artifacts/cache/``.

    Returns
    -------
    pd.Series
        DatetimeIndex → breadth_pct values.
    """
    directory = Path(cache_dir) if cache_dir else _CACHE_DIR
    key = _breadth_cache_key(universe, start, end)
    cache_path = directory / f"breadth_{key}.parquet"

    # Cache hit
    if cache_path.exists():
        try:
            cached = pd.read_parquet(cache_path)
            if "breadth_pct" in cached.columns:
                return cached["breadth_pct"]
        except Exception:
            logger.warning("Breadth cache read failed; recomputing")

    # Compute
    dates = pd.bdate_range(start, end, tz="UTC")
    values = []
    for dt in dates:
        values.append(compute_breadth_pct(dt, universe, features_map))

    series = pd.Series(values, index=dates, name="breadth_pct")

    # Write cache
    try:
        directory.mkdir(parents=True, exist_ok=True)
        series.to_frame().to_parquet(cache_path)
    except Exception:
        logger.warning("Breadth cache write failed", exc_info=True)

    return series
