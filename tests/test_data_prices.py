"""Tests for financer.data.prices — bar normalization and schema.

All tests use local CSV fixtures.  Zero network calls.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from financer.data.prices import EXPECTED_COLUMNS, INDEX_NAME, get_bars, get_market_bars, DataFetchError

FIXTURES = Path(__file__).parent / "fixtures"


def _csv_provider(csv_path: Path):
    """Return a provider callable that reads a local CSV fixture."""
    def provider(ticker: str, start: str, end: str, interval: str) -> pd.DataFrame:
        df = pd.read_csv(csv_path, parse_dates=["timestamp"], index_col="timestamp")
        # Capitalize to simulate yfinance raw output
        df.columns = [c.capitalize() for c in df.columns]
        return df
    return provider


def _empty_provider(ticker: str, start: str, end: str, interval: str) -> pd.DataFrame:
    return pd.DataFrame()


class TestGetBarsColumns:
    def test_columns_are_lowercase(self):
        df = get_bars("AAPL", "2025-11-01", "2026-02-01",
                      provider=_csv_provider(FIXTURES / "AAPL_1d.csv"))
        assert list(df.columns) == EXPECTED_COLUMNS

    def test_no_extra_columns(self):
        df = get_bars("AAPL", "2025-11-01", "2026-02-01",
                      provider=_csv_provider(FIXTURES / "AAPL_1d.csv"))
        assert len(df.columns) == len(EXPECTED_COLUMNS)


class TestGetBarsIndex:
    def test_index_is_datetime(self):
        df = get_bars("AAPL", "2025-11-01", "2026-02-01",
                      provider=_csv_provider(FIXTURES / "AAPL_1d.csv"))
        assert isinstance(df.index, pd.DatetimeIndex)

    def test_index_name(self):
        df = get_bars("AAPL", "2025-11-01", "2026-02-01",
                      provider=_csv_provider(FIXTURES / "AAPL_1d.csv"))
        assert df.index.name == INDEX_NAME

    def test_index_is_tz_aware_utc(self):
        df = get_bars("AAPL", "2025-11-01", "2026-02-01",
                      provider=_csv_provider(FIXTURES / "AAPL_1d.csv"))
        assert df.index.tz is not None
        assert str(df.index.tz) == "UTC"

    def test_monotonic_increasing(self):
        df = get_bars("AAPL", "2025-11-01", "2026-02-01",
                      provider=_csv_provider(FIXTURES / "AAPL_1d.csv"))
        assert df.index.is_monotonic_increasing

    def test_no_duplicate_timestamps(self):
        df = get_bars("AAPL", "2025-11-01", "2026-02-01",
                      provider=_csv_provider(FIXTURES / "AAPL_1d.csv"))
        assert not df.index.has_duplicates


class TestGetBarsDataQuality:
    def test_no_nans_in_ohlc(self):
        df = get_bars("AAPL", "2025-11-01", "2026-02-01",
                      provider=_csv_provider(FIXTURES / "AAPL_1d.csv"))
        for col in ["open", "high", "low", "close"]:
            assert df[col].notna().all(), f"NaN found in {col}"

    def test_has_data(self):
        df = get_bars("AAPL", "2025-11-01", "2026-02-01",
                      provider=_csv_provider(FIXTURES / "AAPL_1d.csv"))
        assert len(df) > 50


class TestGetBarsEmpty:
    def test_empty_provider_returns_correct_schema(self):
        df = get_bars("FAKE", "2025-01-01", "2025-02-01", provider=_empty_provider)
        assert list(df.columns) == EXPECTED_COLUMNS
        assert isinstance(df.index, pd.DatetimeIndex)
        assert df.index.name == INDEX_NAME
        assert len(df) == 0

    def test_exception_provider_raises_error(self):
        def boom(t, s, e, i):
            raise RuntimeError("boom")
        with pytest.raises(DataFetchError, match="Unexpected error fetching FAKE: boom"):
            get_bars("FAKE", "2025-01-01", "2025-02-01", provider=boom)


class TestGetMarketBars:
    def test_delegates_to_get_bars(self):
        calls = []
        def spy_provider(ticker, start, end, interval):
            calls.append(ticker)
            return pd.DataFrame()
        get_market_bars(start="2025-11-01", end="2026-02-01", provider=spy_provider)
        assert calls == ["SPY"]

    def test_custom_market_ticker(self):
        calls = []
        def provider(ticker, start, end, interval):
            calls.append(ticker)
            return pd.DataFrame()
        get_market_bars(market_ticker="QQQ", start="2025-11-01", end="2026-02-01", provider=provider)
        assert calls == ["QQQ"]
