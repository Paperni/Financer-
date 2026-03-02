"""Tests for the RiskScore framework with hysteresis."""

from __future__ import annotations

import pandas as pd
import pytest

from financer.intelligence.risk_score import (
    classify_regime_with_hysteresis,
    compute_breadth_score,
    compute_fast_lane_signal,
    compute_fast_lane_with_hysteresis,
    compute_risk_score,
    compute_trend_score,
    compute_vol_score,
)
from financer.models.enums import Regime


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_spy(
    close: float = 450.0,
    sma_50: float = 440.0,
    sma_200: float = 420.0,
    n_days: int = 30,
    sma200_trend: float = 0.0,
    sma50_trend: float = 0.0,
) -> pd.DataFrame:
    """Build a synthetic SPY DataFrame for testing."""
    idx = pd.bdate_range("2023-01-01", periods=n_days, tz="UTC", name="timestamp")
    return pd.DataFrame(
        {
            "close": [close] * n_days,
            "sma_50": [sma_50 + i * sma50_trend for i in range(n_days)],
            "sma_200": [sma_200 + i * sma200_trend for i in range(n_days)],
        },
        index=idx,
    )


# ── compute_trend_score ─────────────────────────────────────────────────────

class TestComputeTrendScore:
    def test_bullish_above_both_smas_rising(self):
        """Close > SMA-50 > SMA-200, both slopes positive -> high score."""
        df = _make_spy(close=460, sma_50=440, sma_200=420,
                       sma200_trend=0.05, sma50_trend=0.1)
        score = compute_trend_score(df)
        assert score > 60.0

    def test_bearish_below_sma200_falling(self):
        """Close < SMA-200, slopes negative -> low score."""
        df = _make_spy(close=390, sma_50=410, sma_200=420,
                       sma200_trend=-0.1, sma50_trend=-0.2)
        score = compute_trend_score(df)
        assert score < 30.0

    def test_neutral_between_smas_flat(self):
        """Close between SMA-200 and SMA-50, flat slopes -> mid score."""
        df = _make_spy(close=430, sma_50=440, sma_200=420,
                       sma200_trend=0.0, sma50_trend=0.0)
        score = compute_trend_score(df)
        assert 35.0 < score < 65.0

    def test_empty_dataframe_returns_neutral(self):
        df = pd.DataFrame()
        assert compute_trend_score(df) == 50.0

    def test_missing_columns_returns_neutral(self):
        df = pd.DataFrame({"close": [100.0]}, index=pd.bdate_range("2023-01-01", periods=1, tz="UTC"))
        assert compute_trend_score(df) == 50.0

    def test_nan_close_returns_neutral(self):
        df = _make_spy(n_days=5)
        df.iloc[-1, df.columns.get_loc("close")] = float("nan")
        assert compute_trend_score(df) == 50.0

    def test_single_row(self):
        """Single row should still produce a score (no slope data)."""
        df = _make_spy(close=460, sma_50=440, sma_200=420, n_days=1)
        score = compute_trend_score(df)
        # Structure is bullish but slopes default to neutral (50) -> avg ~56.7
        assert score >= 50.0

    def test_score_bounded_0_100(self):
        """Even extreme inputs should clamp to [0, 100]."""
        df_extreme_bull = _make_spy(close=600, sma_50=400, sma_200=300,
                                    sma200_trend=1.0, sma50_trend=2.0)
        assert 0.0 <= compute_trend_score(df_extreme_bull) <= 100.0

        df_extreme_bear = _make_spy(close=200, sma_50=400, sma_200=500,
                                    sma200_trend=-1.0, sma50_trend=-2.0)
        assert 0.0 <= compute_trend_score(df_extreme_bear) <= 100.0

    def test_insufficient_rows_for_slope(self):
        """With < 21 rows, slopes default to neutral but structure still works."""
        df = _make_spy(close=460, sma_50=440, sma_200=420, n_days=5)
        score = compute_trend_score(df)
        # Structure bullish (70+) but slopes are 50 each -> avg ~56-57
        assert score > 50.0


# ── compute_breadth_score / compute_vol_score ────────────────────────────────

class TestBreadthScore:
    def test_default_returns_neutral(self):
        assert compute_breadth_score() == 50.0

    def test_identity_mapping(self):
        assert compute_breadth_score(75.0) == 75.0

    def test_clamps_above_100(self):
        assert compute_breadth_score(120.0) == 100.0

    def test_clamps_below_0(self):
        assert compute_breadth_score(-10.0) == 0.0

    def test_zero(self):
        assert compute_breadth_score(0.0) == 0.0

    def test_hundred(self):
        assert compute_breadth_score(100.0) == 100.0


class TestVolStub:
    def test_vol_returns_neutral(self):
        assert compute_vol_score() == 50.0


# ── compute_risk_score ──────────────────────────────────────────────────────

class TestComputeRiskScore:
    def test_all_neutral(self):
        """All neutral sub-scores -> 50."""
        assert compute_risk_score(50.0, 50.0, 50.0) == 50.0

    def test_trend_dominant(self):
        """Trend is 60% weight, stubs neutral -> score pulled toward trend."""
        score = compute_risk_score(100.0, 50.0, 50.0)
        assert score == pytest.approx(80.0)

    def test_all_bullish(self):
        assert compute_risk_score(100.0, 100.0, 100.0) == 100.0

    def test_all_bearish(self):
        assert compute_risk_score(0.0, 0.0, 0.0) == 0.0

    def test_clamped_to_bounds(self):
        """Out-of-range inputs are clamped."""
        assert compute_risk_score(150.0, 50.0, 50.0) <= 100.0
        assert compute_risk_score(-50.0, 50.0, 50.0) >= 0.0

    def test_with_stubs_default(self):
        """Using default stub values matches explicit neutral."""
        assert compute_risk_score(75.0) == compute_risk_score(75.0, 50.0, 50.0)


# ── compute_fast_lane_signal ────────────────────────────────────────────────

class TestFastLaneSignal:
    def test_activates_when_above_sma50_with_rising_slope(self):
        """SPY > SMA-50 for 5 days with SMA-50 rising -> True."""
        df = _make_spy(close=460, sma_50=440, sma_200=420,
                       sma50_trend=0.5, n_days=10)
        assert compute_fast_lane_signal(df) is True

    def test_does_not_activate_below_sma50(self):
        """SPY < SMA-50 -> False."""
        df = _make_spy(close=430, sma_50=440, sma_200=420,
                       sma50_trend=0.5, n_days=10)
        assert compute_fast_lane_signal(df) is False

    def test_does_not_activate_flat_sma50(self):
        """SPY > SMA-50 but SMA-50 flat (no positive slope) -> False."""
        df = _make_spy(close=460, sma_50=440, sma_200=420,
                       sma50_trend=0.0, n_days=10)
        assert compute_fast_lane_signal(df) is False

    def test_does_not_activate_falling_sma50(self):
        """SPY > SMA-50 at end but SMA-50 declining -> False."""
        df = _make_spy(close=460, sma_50=455, sma_200=420,
                       sma50_trend=-0.5, n_days=10)
        assert compute_fast_lane_signal(df) is False

    def test_insufficient_days(self):
        df = _make_spy(close=460, sma_50=440, sma_200=420, n_days=3)
        assert compute_fast_lane_signal(df, n_days=5) is False

    def test_empty_dataframe(self):
        assert compute_fast_lane_signal(pd.DataFrame()) is False

    def test_missing_columns(self):
        df = pd.DataFrame({"close": [100.0] * 10},
                          index=pd.bdate_range("2023-01-01", periods=10, tz="UTC"))
        assert compute_fast_lane_signal(df) is False

    def test_nan_in_window_returns_false(self):
        """NaN values in the lookback window -> False."""
        df = _make_spy(close=460, sma_50=440, sma_200=420,
                       sma50_trend=0.5, n_days=10)
        df.iloc[-3, df.columns.get_loc("close")] = float("nan")
        assert compute_fast_lane_signal(df) is False

    def test_nan_sma50_in_window_returns_false(self):
        df = _make_spy(close=460, sma_50=440, sma_200=420,
                       sma50_trend=0.5, n_days=10)
        df.iloc[-2, df.columns.get_loc("sma_50")] = float("nan")
        assert compute_fast_lane_signal(df) is False

    def test_custom_n_days(self):
        """Custom n_days=3 with 3 qualifying bars -> True."""
        df = _make_spy(close=460, sma_50=440, sma_200=420,
                       sma50_trend=0.5, n_days=5)
        assert compute_fast_lane_signal(df, n_days=3) is True

    def test_partial_above_sma50_returns_false(self):
        """Only some days above SMA-50 in the window -> False."""
        df = _make_spy(close=460, sma_50=440, sma_200=420,
                       sma50_trend=0.5, n_days=10)
        # Put one day in the last 5 below SMA-50
        df.iloc[-3, df.columns.get_loc("close")] = 430.0
        assert compute_fast_lane_signal(df) is False

    def test_breadth_gate_blocks_low_breadth(self):
        """SPY conditions met but breadth 40 <= 45 -> False."""
        df = _make_spy(close=460, sma_50=440, sma_200=420,
                       sma50_trend=0.5, n_days=10)
        assert compute_fast_lane_signal(df, breadth_pct=40.0) is False

    def test_breadth_gate_allows_high_breadth(self):
        """SPY conditions met and breadth 50 > 45 -> True."""
        df = _make_spy(close=460, sma_50=440, sma_200=420,
                       sma50_trend=0.5, n_days=10)
        assert compute_fast_lane_signal(df, breadth_pct=50.0) is True

    def test_breadth_gate_skipped_when_none(self):
        """breadth_pct=None skips the gate (backward compat)."""
        df = _make_spy(close=460, sma_50=440, sma_200=420,
                       sma50_trend=0.5, n_days=10)
        assert compute_fast_lane_signal(df, breadth_pct=None) is True

    def test_breadth_gate_exact_threshold(self):
        """breadth_pct exactly at threshold (45) -> blocked (<=)."""
        df = _make_spy(close=460, sma_50=440, sma_200=420,
                       sma50_trend=0.5, n_days=10)
        assert compute_fast_lane_signal(df, breadth_pct=45.0) is False
        assert compute_fast_lane_signal(df, breadth_pct=45.1) is True


# ── compute_fast_lane_with_hysteresis ─────────────────────────────────────

class TestFastLaneHysteresis:
    def _bullish_spy(self) -> pd.DataFrame:
        return _make_spy(close=460, sma_50=440, sma_200=420,
                         sma50_trend=0.5, n_days=10)

    def test_activates_above_enter_threshold(self):
        """breadth 50 > enter=45 with SPY OK -> activates."""
        assert compute_fast_lane_with_hysteresis(
            self._bullish_spy(), breadth_pct=50.0, prev_fast_lane=False
        ) is True

    def test_does_not_activate_below_enter(self):
        """breadth 40 <= enter=45 -> does not activate."""
        assert compute_fast_lane_with_hysteresis(
            self._bullish_spy(), breadth_pct=40.0, prev_fast_lane=False
        ) is False

    def test_stays_active_above_exit(self):
        """prev_active=True, breadth 40 >= exit=38 -> stays active."""
        assert compute_fast_lane_with_hysteresis(
            self._bullish_spy(), breadth_pct=40.0, prev_fast_lane=True
        ) is True

    def test_deactivates_below_exit(self):
        """prev_active=True, breadth 35 < exit=38 -> deactivates."""
        assert compute_fast_lane_with_hysteresis(
            self._bullish_spy(), breadth_pct=35.0, prev_fast_lane=True
        ) is False

    def test_deactivates_when_spy_fails(self):
        """prev_active=True but SPY below SMA-50 -> deactivates."""
        df = _make_spy(close=430, sma_50=440, sma_200=420,
                       sma50_trend=0.5, n_days=10)
        assert compute_fast_lane_with_hysteresis(
            df, breadth_pct=50.0, prev_fast_lane=True
        ) is False

    def test_exact_exit_boundary(self):
        """breadth exactly at exit=38 -> stays active (>=)."""
        assert compute_fast_lane_with_hysteresis(
            self._bullish_spy(), breadth_pct=38.0, prev_fast_lane=True
        ) is True


# ── classify_regime_with_hysteresis ─────────────────────────────────────────

class TestHysteresis:
    # -- Basic threshold transitions --

    def test_risk_on_entry_at_65(self):
        """Score 65+ from CAUTIOUS -> RISK_ON."""
        assert classify_regime_with_hysteresis(65.0, Regime.CAUTIOUS) == Regime.RISK_ON

    def test_risk_on_stays_above_exit(self):
        """Score 56 (above exit=55) from RISK_ON -> stays RISK_ON."""
        assert classify_regime_with_hysteresis(56.0, Regime.RISK_ON) == Regime.RISK_ON

    def test_risk_on_exits_below_55(self):
        """Score 54 (below exit=55) from RISK_ON -> CAUTIOUS."""
        assert classify_regime_with_hysteresis(54.0, Regime.RISK_ON) == Regime.CAUTIOUS

    def test_risk_off_entry_at_35(self):
        """Score 35 from CAUTIOUS -> RISK_OFF."""
        assert classify_regime_with_hysteresis(35.0, Regime.CAUTIOUS) == Regime.RISK_OFF

    def test_risk_off_stays_below_exit(self):
        """Score 44 (below exit=45) from RISK_OFF -> stays RISK_OFF."""
        assert classify_regime_with_hysteresis(44.0, Regime.RISK_OFF) == Regime.RISK_OFF

    def test_risk_off_exits_above_45(self):
        """Score 46 (above exit=45) from RISK_OFF -> CAUTIOUS."""
        assert classify_regime_with_hysteresis(46.0, Regime.RISK_OFF) == Regime.CAUTIOUS

    # -- Dead zone (hysteresis gap) --

    def test_dead_zone_risk_on_side(self):
        """Score 60 is below RISK_ON entry (65) but above exit (55).
        From CAUTIOUS stays CAUTIOUS, from RISK_ON stays RISK_ON."""
        assert classify_regime_with_hysteresis(60.0, Regime.CAUTIOUS) == Regime.CAUTIOUS
        assert classify_regime_with_hysteresis(60.0, Regime.RISK_ON) == Regime.RISK_ON

    def test_dead_zone_risk_off_side(self):
        """Score 40 is above RISK_OFF entry (35) but below exit (45).
        From CAUTIOUS stays CAUTIOUS, from RISK_OFF stays RISK_OFF."""
        assert classify_regime_with_hysteresis(40.0, Regime.CAUTIOUS) == Regime.CAUTIOUS
        assert classify_regime_with_hysteresis(40.0, Regime.RISK_OFF) == Regime.RISK_OFF

    # -- Fast lane --

    def test_fast_lane_lowers_risk_on_threshold(self):
        """Score 56 with fast_lane=True from CAUTIOUS -> RISK_ON (threshold 55)."""
        assert classify_regime_with_hysteresis(56.0, Regime.CAUTIOUS, fast_lane=True) == Regime.RISK_ON

    def test_fast_lane_without_it_stays_cautious(self):
        """Score 56 without fast_lane from CAUTIOUS -> stays CAUTIOUS."""
        assert classify_regime_with_hysteresis(56.0, Regime.CAUTIOUS, fast_lane=False) == Regime.CAUTIOUS

    def test_fast_lane_from_risk_off(self):
        """Fast lane also works when exiting RISK_OFF -> straight to RISK_ON."""
        assert classify_regime_with_hysteresis(56.0, Regime.RISK_OFF, fast_lane=True) == Regime.RISK_ON

    def test_fast_lane_still_needs_minimum(self):
        """Score 50 with fast_lane from CAUTIOUS -> stays CAUTIOUS (below 55)."""
        assert classify_regime_with_hysteresis(50.0, Regime.CAUTIOUS, fast_lane=True) == Regime.CAUTIOUS

    # -- Direct jumps --

    def test_risk_on_drops_to_risk_off(self):
        """Score plunges from RISK_ON straight to RISK_OFF territory."""
        assert classify_regime_with_hysteresis(30.0, Regime.RISK_ON) == Regime.RISK_OFF

    def test_risk_off_jumps_to_risk_on(self):
        """Score surges from RISK_OFF straight to RISK_ON territory."""
        assert classify_regime_with_hysteresis(70.0, Regime.RISK_OFF) == Regime.RISK_ON

    # -- Sequence / multi-step transitions --

    def test_full_cycle_cautious_to_risk_on_to_cautious(self):
        """Simulate a regime cycle through score changes."""
        regime = Regime.CAUTIOUS

        # Score rises to 65 -> RISK_ON
        regime = classify_regime_with_hysteresis(65.0, regime)
        assert regime == Regime.RISK_ON

        # Score dips to 58 -> stays RISK_ON (above exit=55)
        regime = classify_regime_with_hysteresis(58.0, regime)
        assert regime == Regime.RISK_ON

        # Score drops to 50 -> CAUTIOUS (below exit=55)
        regime = classify_regime_with_hysteresis(50.0, regime)
        assert regime == Regime.CAUTIOUS

        # Score drops to 30 -> RISK_OFF
        regime = classify_regime_with_hysteresis(30.0, regime)
        assert regime == Regime.RISK_OFF

        # Score rises to 40 -> stays RISK_OFF (below exit=45)
        regime = classify_regime_with_hysteresis(40.0, regime)
        assert regime == Regime.RISK_OFF

        # Score rises to 50 -> CAUTIOUS (above exit=45)
        regime = classify_regime_with_hysteresis(50.0, regime)
        assert regime == Regime.CAUTIOUS

    def test_fast_lane_accelerated_reentry(self):
        """After RISK_OFF, fast lane allows RISK_ON at 56 instead of 65."""
        regime = Regime.RISK_OFF

        # Score rises to 50 -> CAUTIOUS
        regime = classify_regime_with_hysteresis(50.0, regime)
        assert regime == Regime.CAUTIOUS

        # Score 56 without fast lane -> stays CAUTIOUS
        regime_no_fl = classify_regime_with_hysteresis(56.0, regime)
        assert regime_no_fl == Regime.CAUTIOUS

        # Score 56 WITH fast lane -> RISK_ON
        regime_fl = classify_regime_with_hysteresis(56.0, regime, fast_lane=True)
        assert regime_fl == Regime.RISK_ON

    # -- Boundary values --

    def test_exact_boundaries(self):
        """Test exact threshold values."""
        # Exactly at RISK_ON entry from CAUTIOUS
        assert classify_regime_with_hysteresis(65.0, Regime.CAUTIOUS) == Regime.RISK_ON
        assert classify_regime_with_hysteresis(64.9, Regime.CAUTIOUS) == Regime.CAUTIOUS

        # Exactly at RISK_ON exit from RISK_ON
        assert classify_regime_with_hysteresis(55.0, Regime.RISK_ON) == Regime.RISK_ON
        assert classify_regime_with_hysteresis(54.9, Regime.RISK_ON) == Regime.CAUTIOUS

        # Exactly at RISK_OFF entry from CAUTIOUS
        assert classify_regime_with_hysteresis(35.0, Regime.CAUTIOUS) == Regime.RISK_OFF
        assert classify_regime_with_hysteresis(35.1, Regime.CAUTIOUS) == Regime.CAUTIOUS

        # Exactly at RISK_OFF exit from RISK_OFF
        assert classify_regime_with_hysteresis(45.0, Regime.RISK_OFF) == Regime.RISK_OFF
        assert classify_regime_with_hysteresis(45.1, Regime.RISK_OFF) == Regime.CAUTIOUS
