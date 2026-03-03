"""Walk-Forward A/B evaluation — MIE robustness across rolling windows.

Splits the overall date range into rolling train/test windows, selects the
best config on each train window (MIE disabled), then evaluates the selected
config on the test window with both MIE disabled (baseline) and MIE enabled.

Usage:
    python -m financer.cli.run_walk_forward \
        --leaderboard artifacts/campaigns/swing_v1/leaderboard.csv \
        --top-n 5 \
        --start 2021-01-01 --end 2025-12-31
"""

from __future__ import annotations

import argparse
import ast
import csv
import json
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from financer.analytics.metrics import compute_max_drawdown_pct
from financer.cli.run_campaign import compute_metrics
from financer.cli.run_replay import run_replay
from financer.execution import policy
from financer.models import sizing
from financer.engines.swing import scorecard
from financer.features.build import build_features
from financer.data.prices import get_bars, DataFetchError

try:
    from legacy.data_static import BROAD_STOCKS, BROAD_ETFS
except ImportError:
    BROAD_STOCKS, BROAD_ETFS = [], []

logger = logging.getLogger(__name__)


# ── Split generation ─────────────────────────────────────────────────────────

def generate_splits(
    overall_start: str,
    overall_end: str,
    train_months: int = 24,
    test_months: int = 6,
    step_months: int = 6,
) -> list[dict[str, str]]:
    """Generate rolling train/test date splits.

    Parameters
    ----------
    overall_start, overall_end : str
        Full date range (e.g. "2021-01-01", "2025-12-31").
    train_months, test_months, step_months : int
        Window sizes in months.

    Returns
    -------
    list of dict
        Each dict has keys: train_start, train_end, test_start, test_end.
    """
    start = pd.Timestamp(overall_start)
    end = pd.Timestamp(overall_end)
    splits: list[dict[str, str]] = []

    cursor = start
    while True:
        train_start = cursor
        train_end = train_start + pd.DateOffset(months=train_months) - pd.Timedelta(days=1)
        test_start = train_end + pd.Timedelta(days=1)
        test_end = test_start + pd.DateOffset(months=test_months) - pd.Timedelta(days=1)

        if test_end > end:
            test_end = end

        if test_start > end:
            break

        splits.append({
            "train_start": train_start.strftime("%Y-%m-%d"),
            "train_end": train_end.strftime("%Y-%m-%d"),
            "test_start": test_start.strftime("%Y-%m-%d"),
            "test_end": test_end.strftime("%Y-%m-%d"),
        })

        cursor = cursor + pd.DateOffset(months=step_months)

    return splits


# ── Helpers ──────────────────────────────────────────────────────────────────

def compute_exposure_pct(equity_curve: list[dict[str, Any]]) -> float:
    """Fraction of days with non-zero utilization."""
    if not equity_curve:
        return 0.0
    total = len(equity_curve)
    exposed = sum(1 for pt in equity_curve if pt.get("utilization_pct", 0) > 0)
    return (exposed / total) * 100.0


def load_top_configs(
    leaderboard_path: str,
    top_n: int = 5,
) -> list[dict[str, Any]]:
    """Load top N survived configs from a leaderboard CSV, sorted by expectancy_R desc."""
    path = Path(leaderboard_path)
    if not path.exists():
        raise FileNotFoundError(f"Leaderboard not found: {path}")

    rows = []
    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row.get("survived", "").strip().lower() != "true":
                continue
            rows.append(row)

    # Sort by expectancy_R descending
    rows.sort(key=lambda r: float(r.get("expectancy_R", 0)), reverse=True)
    rows = rows[:top_n]

    configs = []
    for row in rows:
        rsi_band = row.get("rsi_band", "[35, 50]")
        if isinstance(rsi_band, str):
            rsi_band = ast.literal_eval(rsi_band)
        configs.append({
            "score_threshold": int(float(row["score_threshold"])),
            "stop_atr_mult": float(row["stop_atr_mult"]),
            "time_stop_bars": int(float(row["time_stop_bars"])),
            "rsi_band": rsi_band,
            "cautious_size_mult": float(row["cautious_size_mult"]),
        })

    return configs


def _patch_globals(config: dict[str, Any]) -> None:
    """Patch module-level globals to match a config (same pattern as run_campaign.py)."""
    policy.STOP_LOSS_ATR_MULTIPLIER = config["stop_atr_mult"]
    sizing.ATR_STOP_MULTIPLIER = config["stop_atr_mult"]
    policy.TIME_STOP_DAYS = config["time_stop_bars"]
    scorecard.RSI_BAND_LOWER = config["rsi_band"][0]
    scorecard.RSI_BAND_UPPER = config["rsi_band"][1]
    sizing.CAUTIOUS_SIZE_MULT = config["cautious_size_mult"]


def _run_single(
    config: dict[str, Any],
    start: str,
    end: str,
    feature_dfs: dict[str, pd.DataFrame],
    daily_features: dict,
    intelligence_enabled: bool = False,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Run a single replay and return (metrics, mie_attribution)."""
    _patch_globals(config)

    kwargs = {
        "tickers": list(feature_dfs.keys()),
        "start": start,
        "end": end,
        "initial_cash": 100_000.0,
        "precomputed_features": feature_dfs,
        "precomputed_daily_features": daily_features,
        "min_entry_score": config.get("score_threshold", 5),
        "stop_loss_atr_mult": config.get("stop_atr_mult", 1.5),
        "intelligence_enabled": intelligence_enabled,
    }
    for key in ["max_positions", "max_heat_R", "pyramiding_mode", "risk_per_trade_pct", "cautious_size_mult"]:
        if key in config:
            kwargs[key] = config[key]

    result = run_replay(**kwargs)
    empty_attr = {
        "regime_days": {"RISK_ON": 0, "CAUTIOUS": 0, "RISK_OFF": 0},
        "entry_intents_total": 0, "entry_intents_vetoed_by_mie": 0,
        "exits_forced_by_mie": 0, "forced_exit_tickers": [],
        "scorecard_thresholds": [], "position_size_multipliers": [],
    }
    if not result:
        return ({"max_dd_pct": 0.0, "trades": 0, "expectancy_R": 0.0,
                "total_return_pct": 0.0, "exposure_pct": 0.0}, empty_attr)

    portfolio, equity_curve, trade_log, attribution = result
    metrics = compute_metrics(equity_curve, trade_log)
    metrics["total_return_pct"] = ((portfolio.equity / 100_000.0) - 1.0) * 100.0
    metrics["exposure_pct"] = compute_exposure_pct(equity_curve)
    return (metrics, attribution)


# ── Report generation ────────────────────────────────────────────────────────

def _write_stability_report(
    out_dir: Path,
    splits: list[dict[str, str]],
    split_selections: list[dict[str, Any]],
    test_metrics: list[dict[str, Any]],
) -> None:
    """Write stability_report.md summarizing A/B results."""
    baseline_rows = [r for r in test_metrics if r["mode"] == "baseline"]
    mie_rows = [r for r in test_metrics if r["mode"] == "mie"]

    def _median(rows: list[dict], key: str) -> float:
        vals = [r[key] for r in rows]
        return float(pd.Series(vals).median()) if vals else 0.0

    def _worst(rows: list[dict], key: str, fn=min) -> float:
        vals = [r[key] for r in rows]
        return fn(vals) if vals else 0.0

    lines = [
        "# MIE Walk-Forward Stability Report\n",
        f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n",
        f"Splits: {len(splits)} | Train: 24mo | Test: 6mo | Step: 6mo\n",
        "",
        "## Test Window Metrics\n",
        "### Baseline (MIE Disabled)\n",
        "| Split | Period | Return % | Max DD % | Exp R | Exposure % | Trades |",
        "|-------|--------|----------|----------|-------|------------|--------|",
    ]

    for r in baseline_rows:
        sp = splits[r["split_idx"]]
        period = f"{sp['test_start']} - {sp['test_end']}"
        lines.append(
            f"| {r['split_idx']} | {period} | {r['total_return_pct']:>7.2f} | "
            f"{r['max_dd_pct']:>7.2f} | {r['expectancy_R']:>5.2f} | "
            f"{r['exposure_pct']:>9.2f} | {r['trades']:>5} |"
        )

    lines += [
        "",
        "### MIE Enabled\n",
        "| Split | Period | Return % | Max DD % | Exp R | Exposure % | Trades |",
        "|-------|--------|----------|----------|-------|------------|--------|",
    ]

    for r in mie_rows:
        sp = splits[r["split_idx"]]
        period = f"{sp['test_start']} - {sp['test_end']}"
        lines.append(
            f"| {r['split_idx']} | {period} | {r['total_return_pct']:>7.2f} | "
            f"{r['max_dd_pct']:>7.2f} | {r['expectancy_R']:>5.2f} | "
            f"{r['exposure_pct']:>9.2f} | {r['trades']:>5} |"
        )

    # Distribution summary
    lines += [
        "",
        "## Distribution Summary\n",
        "| Metric | Baseline Median | MIE Median | Delta |",
        "|--------|-----------------|------------|-------|",
    ]
    for key in ["total_return_pct", "max_dd_pct", "expectancy_R", "exposure_pct"]:
        b_med = _median(baseline_rows, key)
        m_med = _median(mie_rows, key)
        delta = m_med - b_med
        lines.append(f"| {key} | {b_med:>7.2f} | {m_med:>7.2f} | {delta:>+7.2f} |")

    # Robustness indicators
    b_profitable = sum(1 for r in baseline_rows if r["total_return_pct"] > 0)
    m_profitable = sum(1 for r in mie_rows if r["total_return_pct"] > 0)
    n = len(splits)

    lines += [
        "",
        "## Robustness Indicators\n",
        f"- Profitable windows: Baseline {b_profitable}/{n}, MIE {m_profitable}/{n}",
        f"- Worst 6-month return: Baseline {_worst(baseline_rows, 'total_return_pct'):.2f}%, "
        f"MIE {_worst(mie_rows, 'total_return_pct'):.2f}%",
        f"- Worst max drawdown: Baseline {_worst(baseline_rows, 'max_dd_pct', max):.2f}%, "
        f"MIE {_worst(mie_rows, 'max_dd_pct', max):.2f}%",
    ]

    # Comparison deltas
    lines += [
        "",
        "## Comparison: MIE vs Baseline Deltas\n",
        "| Metric | Median Delta | Worst-Case Delta |",
        "|--------|-------------|------------------|",
    ]
    for key in ["total_return_pct", "max_dd_pct", "expectancy_R", "exposure_pct"]:
        b_med = _median(baseline_rows, key)
        m_med = _median(mie_rows, key)
        b_worst = _worst(baseline_rows, key, min if key != "max_dd_pct" else max)
        m_worst = _worst(mie_rows, key, min if key != "max_dd_pct" else max)
        med_delta = m_med - b_med
        worst_delta = m_worst - b_worst
        lines.append(f"| {key} | {med_delta:>+7.2f} | {worst_delta:>+7.2f} |")

    (out_dir / "stability_report.md").write_text("\n".join(lines), encoding="utf-8")


def _write_attribution_report(
    out_dir: Path,
    splits: list[dict[str, str]],
    split_attributions: list[dict[str, Any]],
) -> None:
    """Write mie_attribution.md and mie_attribution.csv."""
    csv_rows: list[dict[str, Any]] = []
    md_lines = [
        "# MIE Attribution Report\n",
        f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n",
        f"Splits: {len(splits)}\n",
        "",
        "## Per-Split Attribution\n",
    ]

    for sa in split_attributions:
        si = sa["split_idx"]
        sp = splits[si]
        attr = sa.get("attr", {})
        bm = sa.get("baseline_metrics", {})
        mm = sa.get("mie_metrics", {})
        regime_days = attr.get("regime_days", {"RISK_ON": 0, "CAUTIOUS": 0, "RISK_OFF": 0})
        entry_total = attr.get("entry_intents_total", 0)
        entry_vetoed = attr.get("entry_intents_vetoed_by_mie", 0)
        exits_forced = attr.get("exits_forced_by_mie", 0)
        forced_tickers = attr.get("forced_exit_tickers", [])
        thresholds = attr.get("scorecard_thresholds", [])
        multipliers = attr.get("position_size_multipliers", [])

        avg_threshold = sum(thresholds) / len(thresholds) if thresholds else 0.0
        avg_multiplier = sum(multipliers) / len(multipliers) if multipliers else 0.0
        total_days = sum(regime_days.values())

        # CSV row
        csv_rows.append({
            "split_idx": si,
            "period": f"{sp['test_start']} - {sp['test_end']}",
            "risk_on_days": regime_days.get("RISK_ON", 0),
            "cautious_days": regime_days.get("CAUTIOUS", 0),
            "risk_off_days": regime_days.get("RISK_OFF", 0),
            "entry_intents_total": entry_total,
            "entry_intents_vetoed": entry_vetoed,
            "exits_forced_by_mie": exits_forced,
            "avg_scorecard_threshold": round(avg_threshold, 2),
            "avg_position_size_mult": round(avg_multiplier, 2),
            "baseline_return_pct": round(bm.get("total_return_pct", 0), 2),
            "mie_return_pct": round(mm.get("total_return_pct", 0), 2),
            "baseline_trades": bm.get("trades", 0),
            "mie_trades": mm.get("trades", 0),
        })

        # Markdown section
        period = f"{sp['test_start']} → {sp['test_end']}"
        md_lines.append(f"### Split {si}: {period}\n")
        md_lines.append("| Metric | Value |")
        md_lines.append("|--------|-------|")
        md_lines.append(f"| RISK_ON days | {regime_days.get('RISK_ON', 0)} / {total_days} |")
        md_lines.append(f"| CAUTIOUS days | {regime_days.get('CAUTIOUS', 0)} / {total_days} |")
        md_lines.append(f"| RISK_OFF days | {regime_days.get('RISK_OFF', 0)} / {total_days} |")
        md_lines.append(f"| Entry intents (total) | {entry_total} |")
        md_lines.append(f"| Entry intents vetoed by MIE | {entry_vetoed} |")
        md_lines.append(f"| Exits forced by MIE | {exits_forced} |")
        if forced_tickers:
            unique_forced = sorted(set(forced_tickers))
            md_lines.append(f"| Forced exit tickers | {', '.join(unique_forced[:10])}{'...' if len(unique_forced) > 10 else ''} |")
        md_lines.append(f"| Avg scorecard threshold | {avg_threshold:.2f} |")
        md_lines.append(f"| Avg position size mult | {avg_multiplier:.2f} |")
        md_lines.append("")

        # Narrative
        narrative = _generate_split_narrative(si, regime_days, total_days, entry_total,
                                               entry_vetoed, exits_forced, avg_threshold,
                                               avg_multiplier, bm, mm)
        md_lines.append(f"**Narrative:** {narrative}\n")
        md_lines.append("")

    # Write files
    (out_dir / "mie_attribution.md").write_text("\n".join(md_lines), encoding="utf-8")

    if csv_rows:
        with open(out_dir / "mie_attribution.csv", "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(csv_rows[0].keys()))
            writer.writeheader()
            writer.writerows(csv_rows)


def _generate_split_narrative(
    si: int,
    regime_days: dict[str, int],
    total_days: int,
    entry_total: int,
    entry_vetoed: int,
    exits_forced: int,
    avg_threshold: float,
    avg_multiplier: float,
    bm: dict[str, Any],
    mm: dict[str, Any],
) -> str:
    """Generate a short human-readable narrative for a split."""
    parts: list[str] = []

    cautious_pct = (regime_days.get("CAUTIOUS", 0) / total_days * 100) if total_days else 0
    risk_off_pct = (regime_days.get("RISK_OFF", 0) / total_days * 100) if total_days else 0

    if cautious_pct > 30:
        parts.append(f"MIE classified {cautious_pct:.0f}% of days as CAUTIOUS, tightening entry requirements")
    if risk_off_pct > 0:
        parts.append(f"RISK_OFF activated on {regime_days['RISK_OFF']} days, blocking all new entries")

    if entry_vetoed > 0:
        veto_pct = (entry_vetoed / entry_total * 100) if entry_total else 0
        parts.append(f"vetoed {entry_vetoed}/{entry_total} BUY intents ({veto_pct:.0f}%)")

    if exits_forced > 0:
        parts.append(f"force-exited {exits_forced} positions during RISK_OFF regimes")

    ret_delta = mm.get("total_return_pct", 0) - bm.get("total_return_pct", 0)
    dd_delta = mm.get("max_dd_pct", 0) - bm.get("max_dd_pct", 0)

    if abs(ret_delta) < 0.1 and abs(dd_delta) < 0.1:
        parts.append("net impact was negligible — market stayed RISK_ON")
    elif dd_delta < -0.5:
        parts.append(f"reduced max drawdown by {abs(dd_delta):.1f}pp")
    elif ret_delta < -1.0:
        parts.append(f"cost {abs(ret_delta):.1f}pp return in exchange for risk protection")

    if not parts:
        return "MIE remained neutral throughout the window; no meaningful regime changes detected."

    return "; ".join(parts) + "."


# ── Main orchestrator ────────────────────────────────────────────────────────

def run_walk_forward(
    leaderboard_path: str = "artifacts/campaigns/swing_v1/leaderboard.csv",
    top_n: int = 5,
    overall_start: str = "2021-01-01",
    overall_end: str = "2025-12-31",
    train_months: int = 24,
    test_months: int = 6,
    step_months: int = 6,
    wf_id: str | None = None,
    replay_fn=None,
    tickers: list[str] | None = None,
    require_cache: bool = False,
) -> Path:
    """Run walk-forward A/B evaluation.

    Parameters
    ----------
    leaderboard_path : str
        Path to campaign leaderboard CSV with candidate configs.
    top_n : int
        Number of top configs to consider per train window.
    overall_start, overall_end : str
        Full evaluation date range.
    train_months, test_months, step_months : int
        Window parameters.
    wf_id : str, optional
        Override the output directory name.
    replay_fn : callable, optional
        Override run_replay for testing. Signature matches run_replay.

    Returns
    -------
    Path
        Output directory with artifacts.
    """
    if wf_id is None:
        wf_id = f"wf_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

    out_dir = Path("artifacts/walk_forward") / wf_id
    out_dir.mkdir(parents=True, exist_ok=True)

    configs = load_top_configs(leaderboard_path, top_n)
    if not configs:
        raise ValueError("No survived configs found in leaderboard")

    splits = generate_splits(overall_start, overall_end, train_months, test_months, step_months)
    print(f"Walk-forward: {len(splits)} splits, {len(configs)} candidate configs")

    # Pre-compute features for the full range
    print(f"Loading universe and building features for {overall_start} to {overall_end}...")
    skipped_tickers: list[tuple[str, str]] = []

    if tickers is not None:
        # Explicit override — skip preflight, trust caller
        print(f"Using explicit ticker list: {len(tickers)} tickers")
    elif require_cache:
        # Cache-only mode: use full universe, skip network preflight
        tickers = list(dict.fromkeys(BROAD_STOCKS + BROAD_ETFS))
        print(f"Cache-only mode: {len(tickers)} tickers (no preflight)")
    else:
        tickers = list(dict.fromkeys(BROAD_STOCKS + BROAD_ETFS))
        # Preflight: filter active tickers
        end_dt = pd.to_datetime(overall_end)
        preflight_start = (end_dt - pd.Timedelta(days=7)).strftime("%Y-%m-%d")
        active_tickers = []
        for ticker in tickers:
            try:
                bars = get_bars(ticker, start=preflight_start, end=overall_end)
                if not bars.empty:
                    active_tickers.append(ticker)
            except DataFetchError:
                pass
        tickers = active_tickers
        print(f"Active tickers: {len(tickers)}")

    feature_dfs: dict[str, pd.DataFrame] = {}
    for i, ticker in enumerate(tickers, 1):
        try:
            df = build_features(ticker, start=overall_start, end=overall_end, require_cache=require_cache)
            if not df.empty:
                feature_dfs[ticker] = df
        except DataFetchError as e:
            skipped_tickers.append((ticker, str(e)))
        if i % 50 == 0 or i == len(tickers):
            print(f"Features: {i}/{len(tickers)} (loaded: {len(feature_dfs)}, skipped: {len(skipped_tickers)})")

    if skipped_tickers:
        skip_path = out_dir / "skipped_tickers.csv"
        with open(skip_path, "w", newline="") as f:
            import csv as csv_mod
            w = csv_mod.writer(f)
            w.writerow(["ticker", "reason"])
            w.writerows(skipped_tickers)
        print(f"Skipped {len(skipped_tickers)} tickers → {skip_path}")

    # Transpose for daily lookup
    daily_features: dict[Any, dict[str, dict]] = {}
    for ticker, df in feature_dfs.items():
        ticker_dict = df.to_dict("index")
        for d, row_dict in ticker_dict.items():
            if pd.isna(d):
                continue
            ts = pd.to_datetime(d).normalize()
            if ts not in daily_features:
                daily_features[ts] = {}
            daily_features[ts][ticker] = row_dict

    split_selections: list[dict[str, Any]] = []
    test_metrics: list[dict[str, Any]] = []
    split_attributions: list[dict[str, Any]] = []

    for si, split in enumerate(splits):
        print(f"\n--- Split {si}: train {split['train_start']}-{split['train_end']}, "
              f"test {split['test_start']}-{split['test_end']} ---")

        # TRAIN: evaluate all candidate configs, select best
        best_config = None
        best_score = (-float("inf"), float("inf"), float("inf"))

        for ci, cfg in enumerate(configs):
            t0 = time.time()
            m, _a = _run_single(cfg, split["train_start"], split["train_end"],
                            feature_dfs, daily_features, intelligence_enabled=False)
            dt = time.time() - t0
            score = (m["expectancy_R"], -m["max_dd_pct"], -m["exposure_pct"])
            print(f"  Config {ci}: ExpR={m['expectancy_R']:.3f}, DD={m['max_dd_pct']:.1f}%, "
                  f"Exp={m['exposure_pct']:.1f}% ({dt:.1f}s)")

            if score > best_score:
                best_score = score
                best_config = cfg
                best_train_metrics = m

        print(f"  Selected: {best_config}")

        split_selections.append({
            "split_idx": si,
            "train_start": split["train_start"],
            "train_end": split["train_end"],
            "test_start": split["test_start"],
            "test_end": split["test_end"],
            "selected_config": json.dumps(best_config),
            "train_expectancy_R": best_train_metrics["expectancy_R"],
            "train_max_dd_pct": best_train_metrics["max_dd_pct"],
        })

        # TEST: A/B — collect attribution for MIE runs
        split_attr_pair: dict[str, Any] = {"split_idx": si}

        for mode, intel_flag in [("baseline", False), ("mie", True)]:
            t0 = time.time()
            m, attr = _run_single(best_config, split["test_start"], split["test_end"],
                            feature_dfs, daily_features, intelligence_enabled=intel_flag)
            dt = time.time() - t0
            print(f"  Test [{mode}]: Ret={m['total_return_pct']:.2f}%, DD={m['max_dd_pct']:.1f}%, "
                  f"ExpR={m['expectancy_R']:.3f}, Exp={m['exposure_pct']:.1f}% ({dt:.1f}s)")

            test_metrics.append({
                "split_idx": si,
                "mode": mode,
                "total_return_pct": m["total_return_pct"],
                "max_dd_pct": m["max_dd_pct"],
                "expectancy_R": m["expectancy_R"],
                "exposure_pct": m["exposure_pct"],
                "trades": m["trades"],
            })

            if mode == "mie":
                split_attr_pair["attr"] = attr
                split_attr_pair["mie_metrics"] = m
            else:
                split_attr_pair["baseline_metrics"] = m

        split_attributions.append(split_attr_pair)

    # Write outputs
    with open(out_dir / "splits.csv", "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(split_selections[0].keys()))
        writer.writeheader()
        writer.writerows(split_selections)

    with open(out_dir / "test_metrics.csv", "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(test_metrics[0].keys()))
        writer.writeheader()
        writer.writerows(test_metrics)

    _write_stability_report(out_dir, splits, split_selections, test_metrics)
    _write_attribution_report(out_dir, splits, split_attributions)

    print(f"\nArtifacts saved to {out_dir}")
    return out_dir


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="MIE Walk-Forward A/B Evaluation")
    parser.add_argument("--leaderboard", default="artifacts/campaigns/swing_v1/leaderboard.csv")
    parser.add_argument("--top-n", type=int, default=5)
    parser.add_argument("--start", default="2021-01-01")
    parser.add_argument("--end", default="2025-12-31")
    parser.add_argument("--train-months", type=int, default=24)
    parser.add_argument("--test-months", type=int, default=6)
    parser.add_argument("--step-months", type=int, default=6)
    parser.add_argument(
        "--tickers",
        default=None,
        help="Comma-separated ticker list; overrides universe (skips preflight fetch).",
    )
    parser.add_argument(
        "--require-cache",
        action="store_true",
        default=False,
        help="Cache-only mode: do not fetch from network, skip tickers without cached features.",
    )
    parser.add_argument(
        "--smoke",
        action="store_true",
        help="Preset: 2024-2025, 12mo train, 3mo test/step, top_n=3. Overridden by explicit flags.",
    )
    args = parser.parse_args()

    # Apply smoke preset defaults first; explicit flags override them
    start = args.start
    end = args.end
    train_months = args.train_months
    test_months = args.test_months
    step_months = args.step_months
    top_n = args.top_n

    if args.smoke:
        # Only apply smoke defaults where the user didn't provide an explicit value
        # (argparse doesn't easily distinguish "user set" vs "default", so we check
        #  against the parser defaults)
        defaults = parser.parse_args([])  # empty args → all defaults
        if start == defaults.start:
            start = "2024-01-01"
        if end == defaults.end:
            end = "2025-12-31"
        if train_months == defaults.train_months:
            train_months = 12
        if test_months == defaults.test_months:
            test_months = 3
        if step_months == defaults.step_months:
            step_months = 3
        if top_n == defaults.top_n:
            top_n = 3

    ticker_list = [t.strip() for t in args.tickers.split(",")] if args.tickers else None

    run_walk_forward(
        leaderboard_path=args.leaderboard,
        top_n=top_n,
        overall_start=start,
        overall_end=end,
        train_months=train_months,
        test_months=test_months,
        step_months=step_months,
        tickers=ticker_list,
        require_cache=args.require_cache,
    )
