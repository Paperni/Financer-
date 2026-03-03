"""Precompute and cache feature DataFrames for offline campaign/walk-forward runs.

Usage:
    python -m financer.cli.precompute_features \
        --universe-config campaigns/swing_v1.yml \
        --start 2020-01-01 --end 2025-12-31

    python -m financer.cli.precompute_features \
        --tickers AAPL,MSFT,GOOGL \
        --start 2020-01-01 --end 2025-12-31
"""

from __future__ import annotations

import argparse
import json
import time
from datetime import datetime
from pathlib import Path

import yaml

from financer.data.prices import DataFetchError
from financer.features.build import build_features

try:
    from legacy.data_static import BROAD_STOCKS, BROAD_ETFS
except ImportError:
    BROAD_STOCKS, BROAD_ETFS = [], []


def _resolve_tickers(args: argparse.Namespace) -> list[str]:
    """Resolve ticker list from CLI args."""
    if args.tickers:
        return [t.strip() for t in args.tickers.split(",")]

    if args.universe_config:
        path = Path(args.universe_config)
        if not path.exists():
            raise FileNotFoundError(f"Config not found: {path}")
        cfg = yaml.safe_load(path.read_text())
        universe = cfg.get("universe", [])
        if universe:
            return list(dict.fromkeys(universe))

    # Fallback: default universe
    return list(dict.fromkeys(BROAD_STOCKS + BROAD_ETFS))


def run_precompute(
    tickers: list[str],
    start: str,
    end: str,
    timeframe: str = "1d",
    max_failures: int = 25,
) -> Path:
    """Precompute features for all tickers and write a cache manifest.

    Returns the manifest path.
    """
    run_id = f"precompute_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    manifest_dir = Path("artifacts/cache_manifests")
    manifest_dir.mkdir(parents=True, exist_ok=True)

    manifest: dict[str, dict] = {}
    ok_count = 0
    fail_count = 0

    print(f"Precompute: {len(tickers)} tickers, {start} → {end}, timeframe={timeframe}")
    t0 = time.time()

    for i, ticker in enumerate(tickers, 1):
        try:
            df = build_features(ticker, start=start, end=end, timeframe=timeframe)
            rows = len(df)
            if rows > 0:
                manifest[ticker] = {"status": "ok", "rows_cached": rows}
                ok_count += 1
            else:
                manifest[ticker] = {"status": "failed", "reason": "empty", "rows_cached": 0}
                fail_count += 1
        except DataFetchError as e:
            manifest[ticker] = {"status": "failed", "reason": str(e), "rows_cached": 0}
            fail_count += 1
        except Exception as e:
            manifest[ticker] = {"status": "failed", "reason": str(e), "rows_cached": 0}
            fail_count += 1

        if i % 10 == 0 or i == len(tickers):
            print(f"  Progress: {i}/{len(tickers)} (OK: {ok_count}, Failed: {fail_count})")

        if fail_count >= max_failures:
            print(f"  Max failures ({max_failures}) reached — stopping early.")
            break

    elapsed = time.time() - t0
    manifest_path = manifest_dir / f"{run_id}.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"\nPrecompute done in {elapsed:.1f}s. Manifest: {manifest_path}")
    print(f"  OK: {ok_count} | Failed: {fail_count}")
    return manifest_path


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Precompute and cache feature DataFrames")
    parser.add_argument("--tickers", default=None, help="Comma-separated ticker list")
    parser.add_argument("--universe-config", default=None, help="Path to campaign YAML with universe list")
    parser.add_argument("--start", default="2020-01-01")
    parser.add_argument("--end", default="2025-12-31")
    parser.add_argument("--timeframe", default="1d")
    parser.add_argument("--max-failures", type=int, default=25)
    args = parser.parse_args()

    tickers = _resolve_tickers(args)
    run_precompute(
        tickers=tickers,
        start=args.start,
        end=args.end,
        timeframe=args.timeframe,
        max_failures=args.max_failures,
    )
