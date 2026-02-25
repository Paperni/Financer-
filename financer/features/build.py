"""Feature builder — the single entrypoint for engine-ready feature frames.

``build_features()`` composes data adapters and feature modules into a
tidy DataFrame that engines consume.  No strategy logic lives here.

The output is deterministic and identical in backtest and live modes
(given the same provider and date range).
"""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import Any, Callable

import pandas as pd

from financer.data.events import get_earnings_dates, get_event_flags
from financer.data.fundamentals import get_valuation_inputs
from financer.data.prices import get_bars

from . import cache as feature_cache
from .regime import classify_regime
from .relative_strength import add_relative_strength
from .technicals import add_all_technicals, add_sma


# Columns that engines MUST check before entering a position.
# If any of these are NaN, the bar is not entry-ready.
ENTRY_REQUIRED_COLUMNS: list[str] = [
    "atr_14",
    "sma_50",
    "above_50",
    "regime",
    "rs_20",
]

# Columns that must always be present in the output
REQUIRED_COLUMNS: list[str] = [
    # Technicals
    "atr_14",
    "sma_50",
    "sma_200",
    "above_50",
    "above_200",
    "sma50_slope",
    "sma200_slope",
    "roc_20",
    "rsi_14",
    "macd_hist",
    # Relative strength
    "rs_20",
    "rs_60",
    # Regime
    "regime",
    # Events
    "earnings_within_7d",
    "event_impact_score",
    # Valuation
    "peg_proxy",
    "missing_pe",
    "missing_growth",
    "negative_earnings",
    "outlier_growth",
]


def build_features(
    ticker: str,
    start: str,
    end: str,
    timeframe: str = "1d",
    provider: Callable[..., pd.DataFrame] | None = None,
    fundamentals_provider: Callable[[str], dict[str, Any]] | None = None,
    earnings_provider: Callable[[str], list[date]] | None = None,
    market_ticker: str = "SPY",
    use_cache: bool = True,
    cache_dir: Path | None = None,
) -> pd.DataFrame:
    """Build a complete features DataFrame for a single ticker.

    Parameters
    ----------
    ticker : str
        Instrument symbol (e.g. "AAPL").
    start, end : str
        Date strings like "2025-11-01".
    timeframe : str
        Bar interval — "1d", "1h", etc.
    provider : callable, optional
        Bars provider passed to ``get_bars()``.
    fundamentals_provider : callable, optional
        Provider for ``get_valuation_inputs()``.
    earnings_provider : callable, optional
        Provider for ``get_earnings_dates()``.
    market_ticker : str
        Benchmark ticker for regime and RS (default "SPY").
    use_cache : bool
        Whether to read/write parquet cache.
    cache_dir : Path, optional
        Override default cache directory.

    Returns
    -------
    pd.DataFrame
        Index: UTC DatetimeIndex named ``timestamp``.
        Columns: see ``REQUIRED_COLUMNS``.
    """
    # ── 1. Check cache ──────────────────────────────────────────────────
    cache_kw = {"cache_dir": cache_dir} if cache_dir else {}
    if use_cache:
        cached = feature_cache.load(ticker, timeframe, start, end, **cache_kw)
        if cached is not None:
            return cached

    # ── 2. Load bars ────────────────────────────────────────────────────
    # Extra lookback for SMA-200 warmup
    start_dt = pd.Timestamp(start, tz="UTC")
    warmup_start = (start_dt - pd.Timedelta(days=300)).strftime("%Y-%m-%d")

    bars = get_bars(ticker, start=warmup_start, end=end, timeframe=timeframe, provider=provider)
    market_bars = get_bars(market_ticker, start=warmup_start, end=end, timeframe=timeframe, provider=provider)

    if bars.empty:
        return _empty_features(start, end)

    # ── 3. Technicals ───────────────────────────────────────────────────
    add_all_technicals(bars)

    # ── 4. Market regime ────────────────────────────────────────────────
    if not market_bars.empty:
        add_sma(market_bars, 50)
        add_sma(market_bars, 200)
        regime_series = classify_regime(market_bars)
        # Align regime to ticker index
        bars["regime"] = regime_series.reindex(bars.index, method="ffill")
    else:
        bars["regime"] = "RISK_ON"

    # ── 5. Relative strength ────────────────────────────────────────────
    if not market_bars.empty:
        add_relative_strength(bars, market_bars, periods=(20, 60))
    else:
        bars["rs_20"] = float("nan")
        bars["rs_60"] = float("nan")

    # ── 6. Valuation inputs (constant per ticker, repeated per bar) ────
    val = get_valuation_inputs(ticker, provider=fundamentals_provider)
    bars["peg_proxy"] = val.get("peg_proxy")
    flags = val.get("quality_flags", {})
    bars["missing_pe"] = flags.get("missing_pe", True)
    bars["missing_growth"] = flags.get("missing_growth", True)
    bars["negative_earnings"] = flags.get("negative_earnings", False)
    bars["outlier_growth"] = flags.get("outlier_growth", False)

    # ── 7. Event flags ──────────────────────────────────────────────────
    earnings_dates = get_earnings_dates(ticker, start=start, end=end, provider=earnings_provider)
    bars["earnings_within_7d"] = False
    bars["event_impact_score"] = 0.0
    for ed in earnings_dates:
        ed_ts = pd.Timestamp(ed, tz="UTC")
        mask = (bars.index >= ed_ts - pd.Timedelta(days=7)) & (bars.index <= ed_ts)
        bars.loc[mask, "earnings_within_7d"] = True

    # ── 8. Trim warmup and select output range ─────────────────────────
    output_start = pd.Timestamp(start, tz="UTC")
    output_end = pd.Timestamp(end, tz="UTC")
    bars = bars.loc[output_start:output_end]

    # Ensure all required columns exist
    for col in REQUIRED_COLUMNS:
        if col not in bars.columns:
            bars[col] = float("nan")

    # ── 9. Cache result ─────────────────────────────────────────────────
    if use_cache and not bars.empty:
        feature_cache.save(bars, ticker, timeframe, **cache_kw)

    return bars


def _empty_features(start: str, end: str) -> pd.DataFrame:
    """Return an empty DataFrame with all required columns."""
    df = pd.DataFrame(columns=REQUIRED_COLUMNS)
    df.index = pd.DatetimeIndex([], name="timestamp", tz="UTC")
    return df
