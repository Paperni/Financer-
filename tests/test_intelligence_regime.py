"""Tests for financer.intelligence.regime — price-based regime classifier.

All tests use synthetic SPY DataFrames.  Zero network calls.
"""

from __future__ import annotations

from datetime import datetime, timezone

import numpy as np
import pandas as pd
import pytest

from financer.models.enums import Regime
from financer.intelligence.config import IntelligenceConfig, RegimeConfig, RegimeParamsConfig
from financer.intelligence.models import ControlPlan
from financer.intelligence.regime import (
    _RegimeSmoothing,
    _atr_volatility_signal,
    _composite_to_regime,
    _sma200_slope_signal,
    _sma_structure_signal,
    classify_regime_at_date,
)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_spy_df(
    close: float = 450.0,
    sma_50: float = 440.0,
    sma_200: float = 420.0,
    atr_14: float = 5.0,
    n_days: int = 250,
    sma200_trend: float = 0.0,
) -> pd.DataFrame:
    """Build a synthetic SPY DataFrame with constant values.

    Parameters
    ----------
    sma200_trend : float
        Per-day additive drift on sma_200 to simulate slope.
    """
    dates = pd.bdate_range("2022-01-01", periods=n_days, tz="UTC", name="timestamp")
    sma200_vals = [sma_200 + i * sma200_trend for i in range(n_days)]
    df = pd.DataFrame(
        {
            "close": close,
            "sma_50": sma_50,
            "sma_200": sma200_vals,
            "atr_14": atr_14,
        },
        index=dates,
    )
    return df


def _default_config() -> IntelligenceConfig:
    return IntelligenceConfig()


# ── Signal unit tests ────────────────────────────────────────────────────────

class TestSMAStructureSignal:
    def test_above_both_smas(self):
        assert _sma_structure_signal(450, 440, 420) == 1.0

    def test_between_smas(self):
        assert _sma_structure_signal(430, 440, 420) == 0.0

    def test_below_sma200(self):
        assert _sma_structure_signal(410, 440, 420) == -1.0

    def test_nan_sma200_neutral(self):
        assert _sma_structure_signal(450, 440, float("nan")) == 0.0

    def test_nan_sma50_neutral_above_200(self):
        # Above SMA-200 but SMA-50 is NaN -> can't confirm above both
        assert _sma_structure_signal(450, float("nan"), 420) == 0.0


class TestSMA200SlopeSignal:
    def test_positive_slope(self):
        # SMA-200 rising: 400 -> 410 over 20 days
        vals = pd.Series([400.0 + i * 0.5 for i in range(25)])
        assert _sma200_slope_signal(vals, lookback=20, threshold=0.0) == 1.0

    def test_negative_slope(self):
        vals = pd.Series([410.0 - i * 0.5 for i in range(25)])
        assert _sma200_slope_signal(vals, lookback=20, threshold=0.0) == -1.0

    def test_flat_slope(self):
        vals = pd.Series([400.0] * 25)
        assert _sma200_slope_signal(vals, lookback=20, threshold=0.0) == 0.0

    def test_insufficient_data(self):
        vals = pd.Series([400.0] * 5)
        assert _sma200_slope_signal(vals, lookback=20, threshold=0.0) == 0.0


class TestATRVolatilitySignal:
    def test_low_vol(self):
        # atr/close = 5/450 = 1.1% < 1.5% (half of 3%)
        assert _atr_volatility_signal(5.0, 450.0, 0.03) == 1.0

    def test_high_vol(self):
        # atr/close = 20/450 = 4.4% > 3%
        assert _atr_volatility_signal(20.0, 450.0, 0.03) == -1.0

    def test_normal_vol(self):
        # atr/close = 9/450 = 2% -> between 1.5% and 3%
        assert _atr_volatility_signal(9.0, 450.0, 0.03) == 0.0

    def test_nan_atr(self):
        assert _atr_volatility_signal(float("nan"), 450.0, 0.03) == 0.0

    def test_zero_close(self):
        assert _atr_volatility_signal(5.0, 0.0, 0.03) == 0.0


class TestCompositeToRegime:
    def test_risk_on(self):
        assert _composite_to_regime(2.0) == Regime.RISK_ON
        assert _composite_to_regime(3.0) == Regime.RISK_ON

    def test_cautious(self):
        assert _composite_to_regime(1.0) == Regime.CAUTIOUS
        assert _composite_to_regime(0.0) == Regime.CAUTIOUS

    def test_risk_off(self):
        assert _composite_to_regime(-1.0) == Regime.RISK_OFF
        assert _composite_to_regime(-3.0) == Regime.RISK_OFF


# ── classify_regime_at_date ──────────────────────────────────────────────────

class TestClassifyRegimeAtDate:
    def test_risk_on_above_both_smas(self):
        spy = _make_spy_df(close=450, sma_50=440, sma_200=420, atr_14=5.0,
                           sma200_trend=0.05)
        cfg = _default_config()
        date = spy.index[-1]
        plan = classify_regime_at_date(spy, date, cfg)
        assert plan.regime == Regime.RISK_ON

    def test_risk_off_below_sma200(self):
        spy = _make_spy_df(close=400, sma_50=440, sma_200=420, atr_14=5.0,
                           sma200_trend=-0.05)
        cfg = _default_config()
        date = spy.index[-1]
        plan = classify_regime_at_date(spy, date, cfg)
        assert plan.regime == Regime.RISK_OFF

    def test_cautious_between_smas(self):
        # Between SMAs, flat slope, normal vol -> composite = 0 -> CAUTIOUS
        spy = _make_spy_df(close=430, sma_50=440, sma_200=420, atr_14=9.0,
                           sma200_trend=0.0)
        cfg = _default_config()
        date = spy.index[-1]
        plan = classify_regime_at_date(spy, date, cfg)
        assert plan.regime == Regime.CAUTIOUS

    def test_high_atr_pct_degrades(self):
        # Above both SMAs but extremely high vol -> structure=+1, slope=+1, vol=-1 -> composite=+1 -> CAUTIOUS
        spy = _make_spy_df(close=450, sma_50=440, sma_200=420, atr_14=20.0,
                           sma200_trend=0.05)
        cfg = _default_config()
        date = spy.index[-1]
        plan = classify_regime_at_date(spy, date, cfg)
        assert plan.regime == Regime.CAUTIOUS

    def test_negative_slope_degrades(self):
        # Above SMA-200 but strong negative slope
        spy = _make_spy_df(close=430, sma_50=440, sma_200=420, atr_14=9.0,
                           sma200_trend=-0.1)
        cfg = _default_config()
        date = spy.index[-1]
        plan = classify_regime_at_date(spy, date, cfg)
        # structure=0 (between SMAs), slope=-1, vol=0 -> composite=-1 -> RISK_OFF
        assert plan.regime == Regime.RISK_OFF

    def test_control_plan_risk_on_params(self):
        spy = _make_spy_df(close=450, sma_50=440, sma_200=420, atr_14=5.0,
                           sma200_trend=0.05)
        cfg = _default_config()
        plan = classify_regime_at_date(spy, spy.index[-1], cfg)
        assert plan.max_positions == 16
        assert plan.position_size_multiplier == 1.0
        assert plan.scorecard_threshold == 5.0

    def test_control_plan_risk_off_params(self):
        spy = _make_spy_df(close=400, sma_50=440, sma_200=420, atr_14=5.0,
                           sma200_trend=-0.05)
        cfg = _default_config()
        plan = classify_regime_at_date(spy, spy.index[-1], cfg)
        assert plan.max_positions == 0
        assert plan.position_size_multiplier == 0.0
        assert plan.scorecard_threshold == 99.0

    def test_control_plan_cautious_params(self):
        spy = _make_spy_df(close=430, sma_50=440, sma_200=420, atr_14=9.0,
                           sma200_trend=0.0)
        cfg = _default_config()
        plan = classify_regime_at_date(spy, spy.index[-1], cfg)
        assert plan.max_positions == 16
        assert plan.position_size_multiplier == 0.75
        assert plan.scorecard_threshold == 5.5

    def test_missing_spy_returns_neutral(self):
        empty = pd.DataFrame()
        cfg = _default_config()
        plan = classify_regime_at_date(empty, datetime(2022, 6, 1, tzinfo=timezone.utc), cfg)
        assert plan.regime == Regime.RISK_ON  # neutral_plan defaults
        assert plan.max_positions == 10

    def test_no_lookahead(self):
        # Build data where early period is bullish, late period is bearish
        spy = _make_spy_df(close=450, sma_50=440, sma_200=420, atr_14=5.0,
                           sma200_trend=0.05, n_days=250)
        # Override last 50 days to be bearish
        spy.iloc[-50:, spy.columns.get_loc("close")] = 400.0

        cfg = _default_config()
        # Classify at day 200 (before bearish period)
        early_date = spy.index[199]
        plan_early = classify_regime_at_date(spy, early_date, cfg)
        assert plan_early.regime == Regime.RISK_ON

        # Classify at last day (bearish)
        plan_late = classify_regime_at_date(spy, spy.index[-1], cfg)
        assert plan_late.regime in (Regime.RISK_OFF, Regime.CAUTIOUS)

    def test_returns_control_plan_type(self):
        spy = _make_spy_df()
        cfg = _default_config()
        plan = classify_regime_at_date(spy, spy.index[-1], cfg)
        assert isinstance(plan, ControlPlan)

    def test_narrative_populated(self):
        spy = _make_spy_df()
        cfg = _default_config()
        plan = classify_regime_at_date(spy, spy.index[-1], cfg)
        assert len(plan.narrative) > 0
        assert "structure=" in plan.narrative

    def test_cautious_size_mult_not_below_075(self):
        # Force CAUTIOUS regime
        spy = _make_spy_df(close=430, sma_50=440, sma_200=420, atr_14=9.0,
                           sma200_trend=0.0)
        cfg = _default_config()
        plan = classify_regime_at_date(spy, spy.index[-1], cfg)
        assert plan.regime == Regime.CAUTIOUS
        assert plan.position_size_multiplier >= 0.75

    def test_risk_off_blocks_entries_but_allows_stops(self):
        # Force RISK_OFF regime
        spy = _make_spy_df(close=400, sma_50=440, sma_200=420, atr_14=5.0,
                           sma200_trend=-0.05)
        cfg = _default_config()
        plan = classify_regime_at_date(spy, spy.index[-1], cfg)
        assert plan.regime == Regime.RISK_OFF
        assert plan.max_positions == 0  # Blocks new entries
        assert not getattr(plan, 'crash_flag', False)  # Allows exits/stops without auto-flatten


# ── Smoothing ────────────────────────────────────────────────────────────────

class TestRegimeSmoothing:
    def test_no_change_returns_current(self):
        sm = _RegimeSmoothing(confirmation_days=2)
        assert sm.update(Regime.RISK_ON) == Regime.RISK_ON

    def test_single_day_no_transition(self):
        sm = _RegimeSmoothing(confirmation_days=2)
        assert sm.update(Regime.RISK_ON) == Regime.RISK_ON
        # One day of CAUTIOUS is not enough
        assert sm.update(Regime.CAUTIOUS) == Regime.RISK_ON

    def test_confirmed_transition(self):
        sm = _RegimeSmoothing(confirmation_days=2)
        sm.update(Regime.RISK_ON)
        sm.update(Regime.CAUTIOUS)
        result = sm.update(Regime.CAUTIOUS)
        assert result == Regime.CAUTIOUS

    def test_whipsaw_prevented(self):
        sm = _RegimeSmoothing(confirmation_days=2)
        sm.update(Regime.RISK_ON)
        sm.update(Regime.CAUTIOUS)
        # Whipsaw back to RISK_ON before confirming
        result = sm.update(Regime.RISK_ON)
        assert result == Regime.RISK_ON  # stays at original

    def test_smoothing_with_classify(self):
        spy = _make_spy_df(close=450, sma_50=440, sma_200=420, atr_14=5.0,
                           sma200_trend=0.05, n_days=250)
        cfg = _default_config()
        sm = _RegimeSmoothing(confirmation_days=2)

        # First few days should be RISK_ON
        for i in range(5):
            plan = classify_regime_at_date(spy, spy.index[200 + i], cfg, smoothing=sm)
        assert plan.regime == Regime.RISK_ON

    def test_custom_regime_params_from_config(self):
        """Verify that custom RegimeParamsConfig values flow through."""
        cfg = IntelligenceConfig(
            regime_params=RegimeParamsConfig(
                risk_on_max_positions=20,
                cautious_max_positions=3,
                cautious_size_mult=0.25,
            )
        )
        # CAUTIOUS scenario
        spy = _make_spy_df(close=430, sma_50=440, sma_200=420, atr_14=9.0,
                           sma200_trend=0.0)
        plan = classify_regime_at_date(spy, spy.index[-1], cfg)
        assert plan.max_positions == 3
        assert plan.position_size_multiplier == 0.25
