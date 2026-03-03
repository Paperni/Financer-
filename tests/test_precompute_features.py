"""Tests for cache-only mode and precompute features CLI.

All tests are offline — no network access.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from financer.data.prices import DataFetchError, get_bars
from financer.features.build import build_features
from financer.cli.precompute_features import run_precompute


# ── get_bars require_cache tests ─────────────────────────────────────────────

def test_get_bars_require_cache_raises_on_miss(tmp_path):
    """get_bars with require_cache=True must raise DataFetchError when no cache exists."""
    with pytest.raises(DataFetchError, match="Cache miss"):
        get_bars("FAKE_TICKER_NOCACHE", start="2025-01-01", end="2025-01-31",
                 require_cache=True)


def test_get_bars_require_cache_returns_cached(tmp_path):
    """get_bars with require_cache=True succeeds when cache exists."""
    # Seed cache using a fixture provider
    def _provider(ticker, start, end, interval):
        idx = pd.date_range("2025-01-02", periods=5, tz="UTC")
        return pd.DataFrame({
            "Open": [100]*5, "High": [105]*5, "Low": [95]*5,
            "Close": [102]*5, "Volume": [1000]*5,
        }, index=idx)

    # First call with network to prime cache
    df = get_bars("CACHE_TEST_TICKER", start="2025-01-01", end="2025-01-10",
                  provider=_provider)
    assert not df.empty

    # Second call with require_cache should succeed from cache
    df2 = get_bars("CACHE_TEST_TICKER", start="2025-01-01", end="2025-01-10",
                   require_cache=True)
    assert not df2.empty
    assert len(df2) == len(df)


# ── build_features require_cache tests ───────────────────────────────────────

def test_build_features_require_cache_raises_on_miss():
    """build_features with require_cache=True raises when bars not cached."""
    with pytest.raises(DataFetchError, match="Cache miss"):
        build_features("FAKE_NOCACHE_TICKER", start="2025-01-01", end="2025-01-31",
                       require_cache=True, use_cache=False)


# ── precompute manifest tests ────────────────────────────────────────────────

def test_precompute_writes_manifest(tmp_path, monkeypatch):
    """run_precompute writes a manifest JSON with correct status per ticker."""
    # Redirect manifest output directory
    monkeypatch.chdir(tmp_path)
    (tmp_path / "artifacts" / "cache_manifests").mkdir(parents=True)
    (tmp_path / "artifacts" / "data_cache").mkdir(parents=True)
    (tmp_path / "data" / "cache" / "features").mkdir(parents=True)

    call_count = {"n": 0}

    def _mock_build(ticker, start, end, timeframe="1d", **kwargs):
        call_count["n"] += 1
        if ticker == "FAIL_TICKER":
            raise DataFetchError("mock failure")
        idx = pd.date_range(start, periods=5, tz="UTC")
        return pd.DataFrame({"close": [100]*5, "atr_14": [2]*5}, index=idx)

    monkeypatch.setattr("financer.cli.precompute_features.build_features", _mock_build)

    manifest_path = run_precompute(
        tickers=["AAPL", "FAIL_TICKER", "MSFT"],
        start="2025-01-01",
        end="2025-01-31",
    )

    assert manifest_path.exists()
    manifest = json.loads(manifest_path.read_text())

    assert manifest["AAPL"]["status"] == "ok"
    assert manifest["AAPL"]["rows_cached"] == 5
    assert manifest["FAIL_TICKER"]["status"] == "failed"
    assert "mock failure" in manifest["FAIL_TICKER"]["reason"]
    assert manifest["MSFT"]["status"] == "ok"
