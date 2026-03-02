"""Tests for financer.intelligence.data.cache — hit/miss, TTL, keying.

Zero network calls.  Uses tmp_path for isolated cache directories.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from financer.intelligence.data.cache import (
    build_key,
    get_cached,
    invalidate,
    set_cached,
)


class TestBuildKey:
    def test_deterministic(self):
        k1 = build_key("SPY", "1d", "2025-01-01", "2025-12-31")
        k2 = build_key("SPY", "1d", "2025-01-01", "2025-12-31")
        assert k1 == k2

    def test_different_inputs_different_keys(self):
        k1 = build_key("SPY", "1d", "2025-01-01", "2025-12-31")
        k2 = build_key("QQQ", "1d", "2025-01-01", "2025-12-31")
        assert k1 != k2

    def test_provider_tag_varies_key(self):
        k1 = build_key("SPY", provider_tag="yfinance")
        k2 = build_key("SPY", provider_tag="csv_fixture")
        assert k1 != k2

    def test_key_is_hex_string(self):
        k = build_key("AAPL")
        assert len(k) == 24
        assert all(c in "0123456789abcdef" for c in k)


class TestSetAndGet:
    def test_round_trip(self, tmp_path: Path):
        key = build_key("SPY")
        set_cached(key, {"price": 450.0}, cache_dir=tmp_path)
        result = get_cached(key, cache_dir=tmp_path)
        assert result == {"price": 450.0}

    def test_miss_returns_none(self, tmp_path: Path):
        result = get_cached("nonexistent_key", cache_dir=tmp_path)
        assert result is None

    def test_stores_various_types(self, tmp_path: Path):
        for val in [42, "hello", [1, 2, 3], {"a": 1}]:
            key = build_key(str(val))
            set_cached(key, val, cache_dir=tmp_path)
            assert get_cached(key, cache_dir=tmp_path) == val

    def test_creates_directory(self, tmp_path: Path):
        nested = tmp_path / "deep" / "nested"
        key = build_key("TEST")
        set_cached(key, "data", cache_dir=nested)
        assert nested.exists()
        assert get_cached(key, cache_dir=nested) == "data"


class TestTTL:
    def test_expired_returns_none(self, tmp_path: Path):
        key = build_key("EXPIRE")
        set_cached(key, "old_data", cache_dir=tmp_path)

        # Backdate the file modification time
        path = tmp_path / f"{key}.pkl"
        old_time = time.time() - 100
        import os
        os.utime(path, (old_time, old_time))

        result = get_cached(key, cache_dir=tmp_path, ttl_seconds=50)
        assert result is None

    def test_fresh_entry_hits(self, tmp_path: Path):
        key = build_key("FRESH")
        set_cached(key, "new_data", cache_dir=tmp_path)
        result = get_cached(key, cache_dir=tmp_path, ttl_seconds=3600)
        assert result == "new_data"


class TestInvalidate:
    def test_removes_entry(self, tmp_path: Path):
        key = build_key("DELETE_ME")
        set_cached(key, "doomed", cache_dir=tmp_path)
        assert get_cached(key, cache_dir=tmp_path) is not None

        invalidate(key, cache_dir=tmp_path)
        assert get_cached(key, cache_dir=tmp_path) is None

    def test_invalidate_nonexistent_is_noop(self, tmp_path: Path):
        # Should not raise
        invalidate("ghost_key", cache_dir=tmp_path)


class TestCorruption:
    def test_corrupted_file_returns_none(self, tmp_path: Path):
        key = build_key("CORRUPT")
        path = tmp_path / f"{key}.pkl"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"not valid pickle data")

        result = get_cached(key, cache_dir=tmp_path)
        assert result is None
