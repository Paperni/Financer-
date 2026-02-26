"""Tests for financer.data.universe — liquidity and price filtering.

All tests use synthetic DataFrames.  Zero network calls.
"""

from __future__ import annotations

import pandas as pd
import numpy as np
import pytest

from financer.data.universe import filter_universe


def _make_bars(close: float, volume: int, n_bars: int = 20) -> pd.DataFrame:
    """Build a minimal normalized bars DataFrame."""
    dates = pd.date_range("2025-12-01", periods=n_bars, freq="B", tz="UTC")
    return pd.DataFrame(
        {
            "open": close,
            "high": close * 1.01,
            "low": close * 0.99,
            "close": close,
            "volume": volume,
        },
        index=pd.DatetimeIndex(dates, name="timestamp"),
    )


def _fixture_provider(fixture_map: dict[str, pd.DataFrame]):
    """Return a provider that looks up bars from a dict."""
    def provider(ticker: str, start: str, end: str, interval: str) -> pd.DataFrame:
        return fixture_map.get(ticker, pd.DataFrame())
    return provider


class TestFilterUniverse:
    def test_keeps_valid_ticker(self):
        bars = {"AAPL": _make_bars(close=150.0, volume=50_000_000)}
        result = filter_universe(
            ["AAPL"],
            bars_provider=_fixture_provider(bars),
        )
        assert "AAPL" in result

    def test_removes_low_price(self):
        bars = {"CHEAP": _make_bars(close=5.0, volume=50_000_000)}
        result = filter_universe(
            ["CHEAP"],
            bars_provider=_fixture_provider(bars),
            min_price=10.0,
        )
        assert "CHEAP" not in result

    def test_removes_low_volume(self):
        bars = {"THIN": _make_bars(close=100.0, volume=10_000)}
        result = filter_universe(
            ["THIN"],
            bars_provider=_fixture_provider(bars),
            min_avg_dollar_volume=5_000_000.0,
        )
        assert "THIN" not in result

    def test_removes_insufficient_data(self):
        # Only 5 bars, below MIN_BARS_REQUIRED (10)
        bars = {"SHORT": _make_bars(close=100.0, volume=50_000_000, n_bars=5)}
        result = filter_universe(
            ["SHORT"],
            bars_provider=_fixture_provider(bars),
        )
        assert "SHORT" not in result

    def test_multiple_tickers_mixed(self):
        bars = {
            "GOOD": _make_bars(close=200.0, volume=80_000_000),
            "CHEAP": _make_bars(close=3.0, volume=50_000_000),
            "THIN": _make_bars(close=100.0, volume=5_000),
        }
        result = filter_universe(
            ["GOOD", "CHEAP", "THIN"],
            bars_provider=_fixture_provider(bars),
        )
        assert result == ["GOOD"]

    def test_result_is_sorted(self):
        bars = {
            "MSFT": _make_bars(close=400.0, volume=30_000_000),
            "AAPL": _make_bars(close=200.0, volume=50_000_000),
        }
        result = filter_universe(
            ["MSFT", "AAPL"],
            bars_provider=_fixture_provider(bars),
        )
        assert result == sorted(result)

    def test_missing_ticker_excluded(self):
        result = filter_universe(
            ["NONEXISTENT"],
            bars_provider=_fixture_provider({}),
        )
        assert result == []

    def test_custom_thresholds(self):
        bars = {"PENNY": _make_bars(close=2.0, volume=100_000_000)}
        # Lower the price threshold
        result = filter_universe(
            ["PENNY"],
            bars_provider=_fixture_provider(bars),
            min_price=1.0,
        )
        assert "PENNY" in result
