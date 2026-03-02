"""File-based cache with TTL for intelligence data.

Stores pickled objects under ``artifacts/data_cache/intel/``.
Keys are deterministic hashes of (symbol, timeframe, start, end, provider_tag).

Thread-safety: not required — the bot is single-threaded per run.
"""

from __future__ import annotations

import hashlib
import logging
import pickle
import time
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

_DEFAULT_CACHE_DIR = Path("artifacts/data_cache/intel")
_DEFAULT_TTL_SECONDS = 24 * 60 * 60  # 24 hours


def _cache_key(*parts: str) -> str:
    """Build a deterministic cache key from ordered string parts.

    Parameters
    ----------
    *parts : str
        Components that uniquely identify the cached item,
        e.g. ``("SPY", "1d", "2025-01-01", "2025-12-31", "yfinance")``.

    Returns
    -------
    str
        Hex digest suitable for use as a filename.
    """
    raw = "|".join(str(p) for p in parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def get_cached(
    key: str,
    cache_dir: Path | str | None = None,
    ttl_seconds: int = _DEFAULT_TTL_SECONDS,
) -> Optional[Any]:
    """Retrieve a cached value if it exists and has not expired.

    Parameters
    ----------
    key : str
        Cache key (typically from ``_cache_key``).
    cache_dir : Path, optional
        Directory for cache files.  Defaults to ``artifacts/data_cache/intel/``.
    ttl_seconds : int
        Time-to-live in seconds.  Entries older than this are treated as misses.

    Returns
    -------
    Any or None
        The cached object, or ``None`` on miss / expiry / corruption.
    """
    directory = Path(cache_dir) if cache_dir else _DEFAULT_CACHE_DIR
    path = directory / f"{key}.pkl"

    if not path.exists():
        return None

    try:
        age = time.time() - path.stat().st_mtime
        if age > ttl_seconds:
            logger.debug("Cache expired for key %s (age=%.0fs)", key, age)
            return None

        with open(path, "rb") as fh:
            return pickle.load(fh)  # noqa: S301
    except Exception:
        logger.warning("Cache read failed for key %s", key, exc_info=True)
        return None


def set_cached(
    key: str,
    value: Any,
    cache_dir: Path | str | None = None,
) -> None:
    """Write a value to the cache.

    Parameters
    ----------
    key : str
        Cache key.
    value : Any
        Picklable object to store.
    cache_dir : Path, optional
        Directory for cache files.
    """
    directory = Path(cache_dir) if cache_dir else _DEFAULT_CACHE_DIR
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{key}.pkl"

    try:
        with open(path, "wb") as fh:
            pickle.dump(value, fh, protocol=pickle.HIGHEST_PROTOCOL)
    except Exception:
        logger.warning("Cache write failed for key %s", key, exc_info=True)


def invalidate(
    key: str,
    cache_dir: Path | str | None = None,
) -> None:
    """Remove a single cache entry.

    No-op if the entry does not exist.
    """
    directory = Path(cache_dir) if cache_dir else _DEFAULT_CACHE_DIR
    path = directory / f"{key}.pkl"
    try:
        path.unlink(missing_ok=True)
    except Exception:
        logger.warning("Cache invalidation failed for key %s", key, exc_info=True)


def build_key(
    symbol: str,
    timeframe: str = "1d",
    start: str = "",
    end: str = "",
    provider_tag: str = "default",
) -> str:
    """Convenience wrapper: build a cache key from common parameters.

    Parameters
    ----------
    symbol : str
        Ticker or series ID.
    timeframe : str
        Bar interval or data granularity.
    start, end : str
        Date range strings.
    provider_tag : str
        Identifies the data source (for cache separation across providers).

    Returns
    -------
    str
        Deterministic hex-digest key.
    """
    return _cache_key(symbol, timeframe, start, end, provider_tag)
