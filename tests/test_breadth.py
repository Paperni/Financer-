"""Tests for the breadth proxy module."""

from __future__ import annotations

import shutil
from pathlib import Path

import pandas as pd
import pytest

from financer.intelligence.breadth import compute_breadth_pct, compute_breadth_series

# ── Fixtures ─────────────────────────────────────────────────────────────────

UNIVERSE = ["AAPL", "MSFT", "GOOGL", "AMZN", "TSLA"]

# 3 dates: 2023-01-03, 2023-01-04, 2023-01-05 (business days)
_DATES = pd.bdate_range("2023-01-03", periods=3, tz="UTC")


def _make_features_map() -> dict[str, pd.DataFrame]:
    """Build a 5-ticker features_map with known close/sma_200 conditions.

    Date 1 (2023-01-03): AAPL, MSFT, GOOGL, AMZN above; TSLA below -> 80%
    Date 2 (2023-01-04): AAPL, MSFT above; GOOGL, AMZN, TSLA below   -> 40%
    Date 3 (2023-01-05): all below                                     ->  0%
    """
    return {
        "AAPL": pd.DataFrame(
            {"close": [150.0, 155.0, 90.0], "sma_200": [140.0, 150.0, 140.0]},
            index=_DATES,
        ),
        "MSFT": pd.DataFrame(
            {"close": [300.0, 310.0, 250.0], "sma_200": [280.0, 300.0, 280.0]},
            index=_DATES,
        ),
        "GOOGL": pd.DataFrame(
            {"close": [130.0, 115.0, 100.0], "sma_200": [120.0, 120.0, 120.0]},
            index=_DATES,
        ),
        "AMZN": pd.DataFrame(
            {"close": [110.0, 95.0, 80.0], "sma_200": [100.0, 100.0, 100.0]},
            index=_DATES,
        ),
        "TSLA": pd.DataFrame(
            {"close": [180.0, 170.0, 160.0], "sma_200": [200.0, 200.0, 200.0]},
            index=_DATES,
        ),
    }


# ── compute_breadth_pct ──────────────────────────────────────────────────────

class TestComputeBreadthPct:
    def test_all_above(self):
        """All 5 tickers above SMA-200 -> 100%."""
        fm = _make_features_map()
        # Override so all are above on date 1
        fm["TSLA"].iloc[0, fm["TSLA"].columns.get_loc("close")] = 210.0
        assert compute_breadth_pct(_DATES[0], UNIVERSE, fm) == 100.0

    def test_mixed_date1(self):
        """Date 1: 4/5 above -> 80%."""
        fm = _make_features_map()
        assert compute_breadth_pct(_DATES[0], UNIVERSE, fm) == 80.0

    def test_mixed_date2(self):
        """Date 2: 2/5 above -> 40%."""
        fm = _make_features_map()
        assert compute_breadth_pct(_DATES[1], UNIVERSE, fm) == 40.0

    def test_all_below(self):
        """Date 3: 0/5 above -> 0%."""
        fm = _make_features_map()
        assert compute_breadth_pct(_DATES[2], UNIVERSE, fm) == 0.0

    def test_skips_nan_close(self):
        """Ticker with NaN close is excluded from both numerator and denominator."""
        fm = _make_features_map()
        fm["AAPL"].iloc[0, fm["AAPL"].columns.get_loc("close")] = float("nan")
        # Date 1: MSFT, GOOGL, AMZN above (3), TSLA below (1) -> 3/4 = 75%
        assert compute_breadth_pct(_DATES[0], UNIVERSE, fm) == 75.0

    def test_skips_nan_sma200(self):
        """Ticker with NaN sma_200 is excluded."""
        fm = _make_features_map()
        fm["MSFT"].iloc[0, fm["MSFT"].columns.get_loc("sma_200")] = float("nan")
        # Date 1: AAPL, GOOGL, AMZN above (3), TSLA below (1) -> 3/4 = 75%
        assert compute_breadth_pct(_DATES[0], UNIVERSE, fm) == 75.0

    def test_empty_universe(self):
        """Empty universe -> neutral 50%."""
        fm = _make_features_map()
        assert compute_breadth_pct(_DATES[0], [], fm) == 50.0

    def test_missing_ticker_in_features_map(self):
        """Ticker not in features_map is silently skipped."""
        fm = _make_features_map()
        universe_with_extra = UNIVERSE + ["NVDA"]
        # Same result as without NVDA
        assert compute_breadth_pct(_DATES[0], universe_with_extra, fm) == 80.0

    def test_date_before_data(self):
        """Date before any data -> all tickers skipped -> neutral 50%."""
        fm = _make_features_map()
        early = pd.Timestamp("2020-01-01", tz="UTC")
        assert compute_breadth_pct(early, UNIVERSE, fm) == 50.0


# ── compute_breadth_series ───────────────────────────────────────────────────

_TEST_CACHE = Path("artifacts/test_cache_breadth")


@pytest.fixture(autouse=True)
def _clean_test_cache():
    """Remove test cache dir before and after each test."""
    if _TEST_CACHE.exists():
        shutil.rmtree(_TEST_CACHE)
    yield
    if _TEST_CACHE.exists():
        shutil.rmtree(_TEST_CACHE)


class TestComputeBreadthSeries:
    def test_returns_series_correct_length(self):
        fm = _make_features_map()
        series = compute_breadth_series(
            "2023-01-03", "2023-01-05", UNIVERSE, fm, cache_dir=_TEST_CACHE
        )
        assert isinstance(series, pd.Series)
        assert len(series) == 3

    def test_series_values_match_pct(self):
        fm = _make_features_map()
        series = compute_breadth_series(
            "2023-01-03", "2023-01-05", UNIVERSE, fm, cache_dir=_TEST_CACHE
        )
        assert series.iloc[0] == 80.0
        assert series.iloc[1] == 40.0
        assert series.iloc[2] == 0.0

    def test_caching_writes_parquet(self):
        fm = _make_features_map()
        compute_breadth_series(
            "2023-01-03", "2023-01-05", UNIVERSE, fm, cache_dir=_TEST_CACHE
        )
        parquets = list(_TEST_CACHE.glob("breadth_*.parquet"))
        assert len(parquets) == 1

    def test_caching_reads_from_cache(self):
        fm = _make_features_map()
        s1 = compute_breadth_series(
            "2023-01-03", "2023-01-05", UNIVERSE, fm, cache_dir=_TEST_CACHE
        )
        # Second call with empty features_map should still return cached result
        s2 = compute_breadth_series(
            "2023-01-03", "2023-01-05", UNIVERSE, {}, cache_dir=_TEST_CACHE
        )
        # Parquet roundtrip drops freq attribute; compare values only
        pd.testing.assert_series_equal(s1, s2, check_freq=False)

    def test_determinism(self):
        """Same inputs produce identical outputs."""
        fm = _make_features_map()
        s1 = compute_breadth_series(
            "2023-01-03", "2023-01-05", UNIVERSE, fm, cache_dir=_TEST_CACHE
        )
        # Clear cache so it recomputes
        shutil.rmtree(_TEST_CACHE)
        s2 = compute_breadth_series(
            "2023-01-03", "2023-01-05", UNIVERSE, fm, cache_dir=_TEST_CACHE
        )
        pd.testing.assert_series_equal(s1, s2)
