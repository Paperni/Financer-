"""Tests for financer.features — build_features and sub-modules.

All tests use local CSV/JSON fixtures.  Zero network calls.
Tests are timeframe-agnostic (daily fixtures today, hourly later).
"""

from __future__ import annotations

import json
import tempfile
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from financer.features import REQUIRED_COLUMNS, build_features
from financer.features.regime import classify_regime
from financer.features.relative_strength import add_relative_strength
from financer.features.technicals import add_all_technicals, add_atr, add_sma
from financer.models.enums import Regime

FIXTURES = Path(__file__).parent / "fixtures"


# ── Fixture helpers ─────────────────────────────────────────────────────────

def _load_fixture(name: str) -> pd.DataFrame:
    """Load a CSV fixture as a normalized bars DataFrame."""
    df = pd.read_csv(FIXTURES / name, parse_dates=["timestamp"], index_col="timestamp")
    df.index = df.index.tz_localize("UTC")
    df.index.name = "timestamp"
    return df


def _fixture_provider(fixture_map: dict[str, str]):
    """Return a bars provider that reads from named fixtures."""
    loaded: dict[str, pd.DataFrame] = {}
    for ticker, fname in fixture_map.items():
        loaded[ticker] = _load_fixture(fname)

    def provider(ticker: str, start: str, end: str, interval: str) -> pd.DataFrame:
        df = loaded.get(ticker, pd.DataFrame())
        if df.empty:
            return df
        # Capitalize to simulate yfinance raw output
        out = df.copy()
        out.columns = [c.capitalize() for c in out.columns]
        return out
    return provider


def _fundamentals_provider(ticker: str) -> dict:
    data = json.loads((FIXTURES / "AAPL_valuation.json").read_text())
    return data


def _earnings_provider(ticker: str) -> list[date]:
    # Simulate an earnings date in the middle of our fixture range
    return [date(2025, 12, 15)]


PROVIDER = _fixture_provider({"AAPL": "AAPL_1d.csv", "SPY": "SPY_1d.csv"})


# ── build_features integration ──────────────────────────────────────────────

class TestBuildFeatures:
    """Integration tests for the full feature pipeline."""

    @pytest.fixture()
    def features(self, tmp_path):
        return build_features(
            "AAPL",
            start="2025-11-03",
            end="2026-01-28",
            timeframe="1d",
            provider=PROVIDER,
            fundamentals_provider=_fundamentals_provider,
            earnings_provider=_earnings_provider,
            use_cache=False,
        )

    def test_required_columns_present(self, features):
        for col in REQUIRED_COLUMNS:
            assert col in features.columns, f"Missing column: {col}"

    def test_index_is_utc_datetime(self, features):
        assert isinstance(features.index, pd.DatetimeIndex)
        assert features.index.tz is not None
        assert str(features.index.tz) == "UTC"

    def test_index_name(self, features):
        assert features.index.name == "timestamp"

    def test_index_monotonic(self, features):
        assert features.index.is_monotonic_increasing

    def test_has_data(self, features):
        assert len(features) > 30

    def test_regime_values_valid(self, features):
        valid = {Regime.RISK_ON, Regime.CAUTIOUS, Regime.RISK_OFF,
                 Regime.RISK_ON.value, Regime.CAUTIOUS.value, Regime.RISK_OFF.value}
        for val in features["regime"].dropna().unique():
            assert val in valid, f"Invalid regime: {val}"

    def test_boolean_columns_no_nans(self, features):
        for col in ["above_50", "above_200", "earnings_within_7d",
                     "missing_pe", "missing_growth", "negative_earnings", "outlier_growth"]:
            assert features[col].notna().all(), f"NaN in boolean column: {col}"

    def test_peg_proxy_constant(self, features):
        # PEG is a fundamentals field, should be identical across all bars
        unique = features["peg_proxy"].dropna().unique()
        assert len(unique) <= 1

    def test_earnings_within_7d_has_true(self, features):
        # We injected an earnings date of 2025-12-15
        assert features["earnings_within_7d"].any()

    def test_event_impact_score_default(self, features):
        assert (features["event_impact_score"] == 0.0).all()


# ── Technicals unit tests ───────────────────────────────────────────────────

class TestTechnicals:
    @pytest.fixture()
    def bars(self):
        return _load_fixture("AAPL_1d.csv")

    def test_atr_positive_after_warmup(self, bars):
        add_atr(bars, 14)
        # After 14-bar warmup, ATR should be positive
        valid = bars["atr_14"].iloc[14:]
        assert (valid > 0).all()

    def test_sma_50_exists(self, bars):
        add_sma(bars, 50)
        assert "sma_50" in bars.columns
        assert "above_50" in bars.columns

    def test_above_50_is_boolean(self, bars):
        add_sma(bars, 50)
        assert bars["above_50"].dtype == bool

    def test_all_technicals_adds_columns(self, bars):
        add_all_technicals(bars)
        expected = ["atr_14", "sma_50", "sma_200", "above_50", "above_200",
                     "sma50_slope", "sma200_slope", "rsi_14", "macd_hist", "roc_20"]
        for col in expected:
            assert col in bars.columns, f"Missing technical: {col}"

    def test_rsi_range(self, bars):
        add_all_technicals(bars)
        valid_rsi = bars["rsi_14"].dropna()
        assert (valid_rsi >= 0).all()
        assert (valid_rsi <= 100).all()


# ── Relative strength unit tests ────────────────────────────────────────────

class TestRelativeStrength:
    def test_rs_columns_added(self):
        aapl = _load_fixture("AAPL_1d.csv")
        spy = _load_fixture("SPY_1d.csv")
        add_relative_strength(aapl, spy)
        assert "rs_20" in aapl.columns
        assert "rs_60" in aapl.columns

    def test_rs_values_finite_after_warmup(self):
        aapl = _load_fixture("AAPL_1d.csv")
        spy = _load_fixture("SPY_1d.csv")
        add_relative_strength(aapl, spy)
        valid_20 = aapl["rs_20"].iloc[20:]
        assert np.isfinite(valid_20).all()


# ── Regime unit tests ───────────────────────────────────────────────────────

class TestRegime:
    def test_regime_output_length(self):
        spy = _load_fixture("SPY_1d.csv")
        add_sma(spy, 50)
        add_sma(spy, 200)
        regime = classify_regime(spy)
        assert len(regime) == len(spy)

    def test_regime_values_are_enum(self):
        spy = _load_fixture("SPY_1d.csv")
        add_sma(spy, 50)
        add_sma(spy, 200)
        regime = classify_regime(spy)
        valid = {Regime.RISK_ON, Regime.CAUTIOUS, Regime.RISK_OFF}
        for val in regime.dropna().unique():
            assert val in valid

    def test_regime_without_sma_defaults_risk_on(self):
        spy = _load_fixture("SPY_1d.csv")
        regime = classify_regime(spy)
        assert (regime == Regime.RISK_ON).all()


# ── Cache unit tests ────────────────────────────────────────────────────────

class TestCache:
    def test_cache_round_trip(self, tmp_path):
        df = build_features(
            "AAPL",
            start="2025-11-03",
            end="2026-01-28",
            timeframe="1d",
            provider=PROVIDER,
            fundamentals_provider=_fundamentals_provider,
            earnings_provider=_earnings_provider,
            use_cache=True,
            cache_dir=tmp_path,
        )

        # Second call should hit cache
        cached = build_features(
            "AAPL",
            start="2025-11-03",
            end="2026-01-28",
            timeframe="1d",
            provider=PROVIDER,
            fundamentals_provider=_fundamentals_provider,
            earnings_provider=_earnings_provider,
            use_cache=True,
            cache_dir=tmp_path,
        )
        assert len(cached) == len(df)
        assert list(cached.columns) == list(df.columns)

    def test_cache_file_created(self, tmp_path):
        build_features(
            "AAPL",
            start="2025-11-03",
            end="2026-01-28",
            timeframe="1d",
            provider=PROVIDER,
            fundamentals_provider=_fundamentals_provider,
            earnings_provider=_earnings_provider,
            use_cache=True,
            cache_dir=tmp_path,
        )
        parquet_file = tmp_path / "AAPL_1d.parquet"
        assert parquet_file.exists()
