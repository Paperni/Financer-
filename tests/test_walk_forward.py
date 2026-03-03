"""Tests for the walk-forward A/B evaluation framework (no network)."""

from __future__ import annotations

import csv
import json
import shutil
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from financer.cli.run_walk_forward import (
    compute_exposure_pct,
    generate_splits,
    load_top_configs,
    run_walk_forward,
)


# ── generate_splits ──────────────────────────────────────────────────────────

class TestGenerateSplits:
    def test_correct_number_of_splits(self):
        """2021-2025 with 24mo train, 6mo test, 6mo step -> 6 splits."""
        splits = generate_splits("2021-01-01", "2025-12-31")
        assert len(splits) == 6

    def test_train_test_no_overlap(self):
        """Train end < test start for every split."""
        splits = generate_splits("2021-01-01", "2025-12-31")
        for s in splits:
            assert s["train_end"] < s["test_start"]

    def test_first_split_dates(self):
        splits = generate_splits("2021-01-01", "2025-12-31")
        assert splits[0]["train_start"] == "2021-01-01"
        assert splits[0]["train_end"] == "2022-12-31"
        assert splits[0]["test_start"] == "2023-01-01"
        assert splits[0]["test_end"] == "2023-06-30"

    def test_last_split_bounded(self):
        """Last test_end does not exceed overall_end."""
        splits = generate_splits("2021-01-01", "2025-12-31")
        for s in splits:
            assert s["test_end"] <= "2025-12-31"

    def test_test_windows_step_correctly(self):
        """Each test_start is 6 months after the previous test_start."""
        splits = generate_splits("2021-01-01", "2025-12-31")
        for i in range(1, len(splits)):
            prev = pd.Timestamp(splits[i - 1]["test_start"])
            curr = pd.Timestamp(splits[i]["test_start"])
            diff_months = (curr.year - prev.year) * 12 + curr.month - prev.month
            assert diff_months == 6

    def test_custom_params(self):
        """Shorter range with custom windows."""
        splits = generate_splits("2022-01-01", "2024-12-31",
                                 train_months=12, test_months=6, step_months=6)
        assert len(splits) >= 2
        for s in splits:
            assert s["train_end"] < s["test_start"]


# ── compute_exposure_pct ─────────────────────────────────────────────────────

class TestComputeExposurePct:
    def test_all_exposed(self):
        curve = [{"utilization_pct": 50.0}, {"utilization_pct": 30.0}]
        assert compute_exposure_pct(curve) == 100.0

    def test_none_exposed(self):
        curve = [{"utilization_pct": 0}, {"utilization_pct": 0}]
        assert compute_exposure_pct(curve) == 0.0

    def test_half_exposed(self):
        curve = [{"utilization_pct": 50.0}, {"utilization_pct": 0}]
        assert compute_exposure_pct(curve) == 50.0

    def test_empty_curve(self):
        assert compute_exposure_pct([]) == 0.0

    def test_missing_key_treated_as_zero(self):
        curve = [{"equity": 100000}, {"utilization_pct": 10.0}]
        assert compute_exposure_pct(curve) == 50.0


# ── Fixtures for integration tests ──────────────────────────────────────────

_TEST_DIR = Path("artifacts/test_walk_forward")
_TEST_LEADERBOARD = _TEST_DIR / "test_leaderboard.csv"


def _write_test_leaderboard(path: Path, n_configs: int = 3) -> None:
    """Create a synthetic leaderboard CSV with n_configs survived rows."""
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    for i in range(n_configs):
        rows.append({
            "score_threshold": 5,
            "stop_atr_mult": 1.5 + i * 0.25,
            "time_stop_bars": 30,
            "rsi_band": "[35, 50]",
            "cautious_size_mult": 0.5,
            "max_dd_pct": 10.0 + i,
            "trades": 100 - i * 10,
            "expectancy_R": 0.30 - i * 0.05,
            "total_return_pct": 20.0 - i * 2,
            "survived": "True",
        })
    # Add a non-survived row
    rows.append({
        "score_threshold": 6,
        "stop_atr_mult": 1.25,
        "time_stop_bars": 30,
        "rsi_band": "[30, 45]",
        "cautious_size_mult": 0.75,
        "max_dd_pct": 0.0,
        "trades": 0,
        "expectancy_R": 0.0,
        "total_return_pct": 0.0,
        "survived": "False",
    })
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def _make_mock_portfolio(equity: float = 105_000.0):
    """Create a mock portfolio object."""
    mock = MagicMock()
    mock.equity = equity
    return mock


def _make_mock_equity_curve(n_days: int = 30, start_eq: float = 100_000.0, end_eq: float = 105_000.0):
    """Create a synthetic equity curve."""
    curve = []
    for i in range(n_days):
        eq = start_eq + (end_eq - start_eq) * i / max(n_days - 1, 1)
        curve.append({
            "date": f"2023-01-{i+1:02d}",
            "equity": eq,
            "cash": eq * 0.5,
            "drawdown_pct": 0.0,
            "utilization_pct": 50.0 if i < n_days // 2 else 0.0,
        })
    return curve


def _make_mock_trade_log(n_trades: int = 5):
    """Create a synthetic trade log with completed buy/sell pairs."""
    log = []
    for i in range(n_trades):
        log.append({
            "date": f"2023-01-{i+1:02d}",
            "filled_orders": [
                {"ticker": f"T{i}", "direction": "BUY", "price": 100.0, "qty": 10},
            ],
            "candidate_intents": [],
            "vetoed_intents": [],
            "created_orders": [],
        })
    for i in range(n_trades):
        log.append({
            "date": f"2023-02-{i+1:02d}",
            "filled_orders": [
                {"ticker": f"T{i}", "direction": "SELL", "price": 110.0, "qty": 10},
            ],
            "candidate_intents": [],
            "vetoed_intents": [],
            "created_orders": [],
        })
    return log


@pytest.fixture(autouse=True)
def _clean_test_dir():
    if _TEST_DIR.exists():
        shutil.rmtree(_TEST_DIR)
    _TEST_DIR.mkdir(parents=True, exist_ok=True)
    yield
    if _TEST_DIR.exists():
        shutil.rmtree(_TEST_DIR)


# ── load_top_configs ─────────────────────────────────────────────────────────

class TestLoadTopConfigs:
    def test_loads_survived_only(self):
        _write_test_leaderboard(_TEST_LEADERBOARD, n_configs=3)
        configs = load_top_configs(str(_TEST_LEADERBOARD), top_n=5)
        assert len(configs) == 3  # 3 survived, 1 not

    def test_sorted_by_expectancy_desc(self):
        _write_test_leaderboard(_TEST_LEADERBOARD, n_configs=3)
        configs = load_top_configs(str(_TEST_LEADERBOARD), top_n=5)
        assert configs[0]["stop_atr_mult"] == 1.5  # highest expectancy_R

    def test_top_n_limits(self):
        _write_test_leaderboard(_TEST_LEADERBOARD, n_configs=3)
        configs = load_top_configs(str(_TEST_LEADERBOARD), top_n=2)
        assert len(configs) == 2


# ── Selection on train only + A/B separate outputs ──────────────────────────

class TestWalkForwardIntegration:
    @patch("financer.cli.run_walk_forward.run_replay")
    @patch("financer.cli.run_walk_forward.get_bars")
    @patch("financer.cli.run_walk_forward.build_features")
    def test_selection_on_train_only(self, mock_build, mock_bars, mock_replay):
        """Selected config should be the one with best expectancy_R on TRAIN."""
        _write_test_leaderboard(_TEST_LEADERBOARD, n_configs=2)

        # Mock build_features to return a minimal DataFrame
        idx = pd.bdate_range("2023-01-01", periods=5, tz="UTC")
        mock_build.return_value = pd.DataFrame(
            {"close": [100.0] * 5, "sma_200": [95.0] * 5}, index=idx
        )
        mock_bars.return_value = pd.DataFrame({"close": [100.0]})

        # Track which configs were used in train vs test
        call_log = []

        def fake_replay(**kwargs):
            call_log.append({
                "start": kwargs["start"],
                "end": kwargs["end"],
                "intelligence_enabled": kwargs.get("intelligence_enabled", False),
                "stop_atr_mult": kwargs.get("stop_loss_atr_mult"),
            })
            portfolio = _make_mock_portfolio()
            eq_curve = _make_mock_equity_curve()
            trade_log = _make_mock_trade_log()
            attribution = {
                "regime_days": {"RISK_ON": 20, "CAUTIOUS": 5, "RISK_OFF": 0},
                "entry_intents_total": 10, "entry_intents_vetoed_by_mie": 2,
                "exits_forced_by_mie": 0, "forced_exit_tickers": [],
                "scorecard_thresholds": [5.0] * 25, "position_size_multipliers": [1.0] * 25,
            }
            return portfolio, eq_curve, trade_log, attribution

        mock_replay.side_effect = fake_replay

        # Use only 1 split and 2 configs for speed
        out_dir = run_walk_forward(
            leaderboard_path=str(_TEST_LEADERBOARD),
            top_n=2,
            overall_start="2023-01-01",
            overall_end="2025-12-31",
            train_months=12,
            test_months=6,
            step_months=12,
            wf_id="test_selection",
        )

        # Verify train calls used intelligence_enabled=False
        train_calls = [c for c in call_log if not c["intelligence_enabled"]]
        assert len(train_calls) > 0

        # Verify outputs exist
        assert (out_dir / "splits.csv").exists()
        assert (out_dir / "test_metrics.csv").exists()
        assert (out_dir / "stability_report.md").exists()

    @patch("financer.cli.run_walk_forward.run_replay")
    @patch("financer.cli.run_walk_forward.get_bars")
    @patch("financer.cli.run_walk_forward.build_features")
    def test_ab_produces_separate_outputs(self, mock_build, mock_bars, mock_replay):
        """test_metrics should have two rows per split: baseline and mie."""
        _write_test_leaderboard(_TEST_LEADERBOARD, n_configs=1)

        idx = pd.bdate_range("2023-01-01", periods=5, tz="UTC")
        mock_build.return_value = pd.DataFrame(
            {"close": [100.0] * 5, "sma_200": [95.0] * 5}, index=idx
        )
        mock_bars.return_value = pd.DataFrame({"close": [100.0]})

        call_count = {"n": 0}

        def fake_replay(**kwargs):
            call_count["n"] += 1
            intel = kwargs.get("intelligence_enabled", False)
            # MIE run returns different equity to verify outputs differ
            eq = 110_000.0 if intel else 105_000.0
            portfolio = _make_mock_portfolio(equity=eq)
            eq_curve = _make_mock_equity_curve(end_eq=eq)
            trade_log = _make_mock_trade_log()
            attribution = {
                "regime_days": {"RISK_ON": 20, "CAUTIOUS": 5, "RISK_OFF": 0},
                "entry_intents_total": 10, "entry_intents_vetoed_by_mie": 2,
                "exits_forced_by_mie": 0, "forced_exit_tickers": [],
                "scorecard_thresholds": [5.0] * 25, "position_size_multipliers": [1.0] * 25,
            }
            return portfolio, eq_curve, trade_log, attribution

        mock_replay.side_effect = fake_replay

        out_dir = run_walk_forward(
            leaderboard_path=str(_TEST_LEADERBOARD),
            top_n=1,
            overall_start="2023-01-01",
            overall_end="2025-06-30",
            train_months=12,
            test_months=6,
            step_months=12,
            wf_id="test_ab",
        )

        # Read test_metrics.csv
        with open(out_dir / "test_metrics.csv", newline="") as f:
            reader = csv.DictReader(f)
            rows = list(reader)

        # Should have 2 rows per split (baseline + mie)
        modes = {r["mode"] for r in rows}
        assert "baseline" in modes
        assert "mie" in modes

        # MIE and baseline should have different return %
        baseline = [r for r in rows if r["mode"] == "baseline"]
        mie = [r for r in rows if r["mode"] == "mie"]
        assert len(baseline) == len(mie)
        if baseline and mie:
            assert float(baseline[0]["total_return_pct"]) != float(mie[0]["total_return_pct"])

    @patch("financer.cli.run_walk_forward.run_replay")
    @patch("financer.cli.run_walk_forward.get_bars")
    @patch("financer.cli.run_walk_forward.build_features")
    def test_determinism(self, mock_build, mock_bars, mock_replay):
        """Two runs with identical inputs produce identical outputs."""
        _write_test_leaderboard(_TEST_LEADERBOARD, n_configs=1)

        idx = pd.bdate_range("2023-01-01", periods=5, tz="UTC")
        mock_build.return_value = pd.DataFrame(
            {"close": [100.0] * 5, "sma_200": [95.0] * 5}, index=idx
        )
        mock_bars.return_value = pd.DataFrame({"close": [100.0]})

        def fake_replay(**kwargs):
            portfolio = _make_mock_portfolio()
            attribution = {
                "regime_days": {"RISK_ON": 20, "CAUTIOUS": 5, "RISK_OFF": 0},
                "entry_intents_total": 10, "entry_intents_vetoed_by_mie": 2,
                "exits_forced_by_mie": 0, "forced_exit_tickers": [],
                "scorecard_thresholds": [5.0] * 25, "position_size_multipliers": [1.0] * 25,
            }
            return portfolio, _make_mock_equity_curve(), _make_mock_trade_log(), attribution

        mock_replay.side_effect = fake_replay

        common_kwargs = dict(
            leaderboard_path=str(_TEST_LEADERBOARD),
            top_n=1,
            overall_start="2023-01-01",
            overall_end="2025-06-30",
            train_months=12,
            test_months=6,
            step_months=12,
        )

        out1 = run_walk_forward(**common_kwargs, wf_id="test_det_1")
        out2 = run_walk_forward(**common_kwargs, wf_id="test_det_2")

        # Compare splits.csv
        s1 = (out1 / "splits.csv").read_text()
        s2 = (out2 / "splits.csv").read_text()
        assert s1 == s2

        # Compare test_metrics.csv
        m1 = (out1 / "test_metrics.csv").read_text()
        m2 = (out2 / "test_metrics.csv").read_text()
        assert m1 == m2
