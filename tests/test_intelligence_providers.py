"""Tests for financer.intelligence.data.providers — graceful degradation.

Zero network calls.  All data sources are mocked via provider injection.
"""

from __future__ import annotations

import pandas as pd
import pytest

from financer.intelligence.data.providers import (
    fetch_multiple_tickers,
    fetch_price_data,
    fetch_yield_curve,
)


# ── Fixtures ─────────────────────────────────────────────────────────────────

def _ok_provider(ticker: str, start: str, end: str, interval: str) -> pd.DataFrame:
    """Provider that returns a minimal valid DataFrame."""
    idx = pd.date_range("2025-01-01", periods=5, freq="B", tz="UTC", name="timestamp")
    return pd.DataFrame(
        {"Open": [100] * 5, "High": [105] * 5, "Low": [95] * 5,
         "Close": [102] * 5, "Volume": [1_000_000] * 5},
        index=idx,
    )


def _empty_provider(ticker: str, start: str, end: str, interval: str) -> pd.DataFrame:
    """Provider that returns empty DataFrame."""
    return pd.DataFrame()


def _boom_provider(ticker: str, start: str, end: str, interval: str) -> pd.DataFrame:
    """Provider that raises an exception."""
    raise RuntimeError("network down")


# ── fetch_price_data ─────────────────────────────────────────────────────────

class TestFetchPriceData:
    def test_returns_dataframe_on_success(self):
        # Unique ticker/date combos avoid parquet cache collisions in get_bars
        df = fetch_price_data("INTL_OK", "2099-01-01", "2099-02-01",
                              provider=_ok_provider)
        assert df is not None
        assert len(df) == 5
        assert "close" in df.columns

    def test_empty_provider_returns_empty(self):
        df = fetch_price_data("INTL_EMPTY", "2099-01-01", "2099-02-01",
                              provider=_empty_provider)
        # get_bars returns empty but valid schema, which is not None
        assert df is not None
        assert len(df) == 0

    def test_exception_returns_none(self):
        result = fetch_price_data("INTL_BOOM", "2099-01-01", "2099-02-01",
                                  provider=_boom_provider)
        assert result is None


# ── fetch_multiple_tickers ───────────────────────────────────────────────────

class TestFetchMultipleTickers:
    def test_returns_dict_of_dataframes(self):
        results = fetch_multiple_tickers(
            ["INTL_A", "INTL_B"], "2099-01-01", "2099-02-01",
            provider=_ok_provider,
        )
        assert "INTL_A" in results
        assert "INTL_B" in results
        assert len(results) == 2

    def test_skips_failed_tickers(self):
        def _mixed(ticker, start, end, interval):
            if ticker == "INTL_BAD":
                raise RuntimeError("fail")
            return _ok_provider(ticker, start, end, interval)

        results = fetch_multiple_tickers(
            ["INTL_C", "INTL_BAD", "INTL_D"], "2099-01-01", "2099-02-01",
            provider=_mixed,
        )
        assert "INTL_C" in results
        assert "INTL_D" in results
        assert "INTL_BAD" not in results

    def test_empty_list(self):
        results = fetch_multiple_tickers(
            [], "2025-01-01", "2025-02-01", provider=_ok_provider,
        )
        assert results == {}


# ── fetch_yield_curve ────────────────────────────────────────────────────────

class TestFetchYieldCurve:
    def test_with_provider(self):
        def mock_fred(series_id, lookback_days):
            return 0.42

        result = fetch_yield_curve(provider=mock_fred)
        assert result == pytest.approx(0.42)

    def test_provider_returns_none(self):
        def mock_fred(series_id, lookback_days):
            return None

        result = fetch_yield_curve(provider=mock_fred)
        assert result is None

    def test_provider_raises_returns_none(self):
        def mock_fred(series_id, lookback_days):
            raise RuntimeError("FRED down")

        result = fetch_yield_curve(provider=mock_fred)
        assert result is None

    def test_no_provider_no_apikey_returns_none(self, monkeypatch):
        """Without fredapi installed or API key, should return None."""
        monkeypatch.delenv("FRED_API_KEY", raising=False)
        # This will either hit "no API key" path or ImportError for fredapi
        result = fetch_yield_curve(api_key=None, provider=None)
        assert result is None
