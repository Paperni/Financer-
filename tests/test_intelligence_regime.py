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



# ── classify_regime_at_date ──────────────────────────────────────────────────

from financer.intelligence.regime import (
    _RegimeSmoothing,
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


# ── classify_regime_at_date (Boolean Logic) ──────────────────────────────────

class TestClassifyRegimeAtDate:
    def test_risk_off_because_price_below_sma200(self):
        # Bullish slope (+0.05), reasonable ATR (5.0 / 400 = 1.25%)
        # But close < sma200 forcing RISK_OFF immediately
        spy = _make_spy_df(close=400, sma_50=440, sma_200=420, atr_14=5.0,
                           sma200_trend=0.05)
        cfg = _default_config()
        date = spy.index[-1]
        plan = classify_regime_at_date(spy, date, cfg)
        assert plan.regime == Regime.RISK_OFF

    def test_risk_off_because_atr_too_high(self):
        # Above both SMAs (close=450, 50=440, 200=420), bullish slope (+0.05)
        # But ATR% is 20/450 = 4.4% (Threshold defaults to 3.0%), triggering RISK_OFF
        spy = _make_spy_df(close=450, sma_50=440, sma_200=420, atr_14=20.0,
                           sma200_trend=0.05)
        cfg = _default_config()
        date = spy.index[-1]
        plan = classify_regime_at_date(spy, date, cfg)
        assert plan.regime == Regime.RISK_OFF

    def test_risk_off_because_negative_slope(self):
        # Above both SMAs, low volatility
        # But strongly negative SMA200 slope, triggering RISK_OFF
        spy = _make_spy_df(close=450, sma_50=440, sma_200=420, atr_14=5.0,
                           sma200_trend=-0.05)
        cfg = _default_config()
        date = spy.index[-1]
        plan = classify_regime_at_date(spy, date, cfg)
        assert plan.regime == Regime.RISK_OFF

    def test_risk_on_all_bullish_conditions_met(self):
        # Price > SMA50 > SMA200 (450 > 440 > 420)
        # Low volatility (1.1%) AND Positive slope (+0.05 a day) -> RISK_ON
        spy = _make_spy_df(close=450, sma_50=440, sma_200=420, atr_14=5.0,
                           sma200_trend=0.05)
        cfg = _default_config()
        date = spy.index[-1]
        plan = classify_regime_at_date(spy, date, cfg)
        assert plan.regime == Regime.RISK_ON

    def test_cautious_between_smas_bullish_otherwise(self):
        # Price (435) < SMA50 (440) but > SMA200 (432.4 end)
        # Despite bullish slope and vol, fails RISK_ON condition -> falls back to CAUTIOUS
        spy = _make_spy_df(close=435, sma_50=440, sma_200=420, atr_14=5.0,
                           sma200_trend=0.05)
        cfg = _default_config()
        date = spy.index[-1]
        plan = classify_regime_at_date(spy, date, cfg)
        assert plan.regime == Regime.CAUTIOUS

    def test_cautious_price_above_smas_but_flat_slope(self):
        # Price > SMA50 > SMA200
        # Low volatility
        # But SMA200 slope is perfectly 0.0 (fails > 0.0 threshold)
        spy = _make_spy_df(close=450, sma_50=440, sma_200=420, atr_14=5.0,
                           sma200_trend=0.0)
        cfg = _default_config()
        date = spy.index[-1]
        plan = classify_regime_at_date(spy, date, cfg)
        assert plan.regime == Regime.CAUTIOUS

    def test_control_plan_risk_on_params(self):
        # Meets RISK_ON Boolean condition
        spy = _make_spy_df(close=450, sma_50=440, sma_200=420, atr_14=5.0,
                           sma200_trend=0.05)
        cfg = _default_config()
        plan = classify_regime_at_date(spy, spy.index[-1], cfg)
        assert plan.max_positions == 12
        assert plan.position_size_multiplier == 1.0
        assert plan.scorecard_threshold == 4.0
        assert plan.policy.allow_entries is True

    def test_control_plan_risk_off_params(self):
        # Triggers RISK_OFF
        spy = _make_spy_df(close=400, sma_50=440, sma_200=420, atr_14=5.0,
                           sma200_trend=0.05)
        cfg = _default_config()
        plan = classify_regime_at_date(spy, spy.index[-1], cfg)
        assert plan.max_positions == 0
        assert plan.position_size_multiplier == 0.0
        assert plan.scorecard_threshold == 6.0
        assert plan.policy.allow_entries is False

    def test_control_plan_cautious_params(self):
        # Triggers CAUTIOUS (positive vol, flat slope)
        spy = _make_spy_df(close=450, sma_50=440, sma_200=420, atr_14=5.0,
                           sma200_trend=0.0)
        cfg = _default_config()
        plan = classify_regime_at_date(spy, spy.index[-1], cfg)
        assert plan.max_positions == 6
        assert plan.position_size_multiplier == 0.75
        assert plan.scorecard_threshold == 5.0
        assert plan.policy.allow_entries is True

    def test_missing_spy_returns_neutral(self):
        empty = pd.DataFrame()
        cfg = _default_config()
        plan = classify_regime_at_date(empty, datetime(2022, 6, 1, tzinfo=timezone.utc), cfg)
        assert plan.regime == Regime.RISK_ON  # neutral_plan defaults
        assert plan.max_positions == 10

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
        assert "close=" in plan.narrative
        assert "atr%=" in plan.narrative

    def test_risk_off_blocks_entries_but_allows_stops(self):
        # Force RISK_OFF regime via downward slope
        spy = _make_spy_df(close=450, sma_50=440, sma_200=420, atr_14=5.0,
                           sma200_trend=-0.5)
        cfg = _default_config()
        plan = classify_regime_at_date(spy, spy.index[-1], cfg)
        assert plan.regime == Regime.RISK_OFF
        assert plan.max_positions == 0  # Blocks new entries
        assert plan.policy.allow_entries is False
        assert not getattr(plan, 'crash_flag', False)  # Allows exits/stops without auto-flatten


# ── Smoothing ────────────────────────────────────────────────────────────────

class TestRegimeSmoothing:
    def test_no_change_returns_current(self):
        sm = _RegimeSmoothing()
        assert sm.update(Regime.RISK_ON) == Regime.RISK_ON

    def test_risk_on_demands_3_days(self):
        sm = _RegimeSmoothing()
        sm._confirmed_regime = Regime.CAUTIOUS
        assert sm.update(Regime.RISK_ON) == Regime.CAUTIOUS
        assert sm.update(Regime.RISK_ON) == Regime.CAUTIOUS
        assert sm.update(Regime.RISK_ON) == Regime.RISK_ON

    def test_risk_off_demands_2_days(self):
        sm = _RegimeSmoothing()
        assert sm.update(Regime.RISK_OFF) == Regime.RISK_ON
        assert sm.update(Regime.RISK_OFF) == Regime.RISK_OFF

    def test_whipsaw_prevented(self):
        sm = _RegimeSmoothing()
        sm.update(Regime.RISK_OFF)
        # Whipsaw back to RISK_ON before confirming
        result = sm.update(Regime.RISK_ON)
        assert result == Regime.RISK_ON  # resets pending but returns previously confirmed RISK_ON

    def test_smoothing_with_classify(self):
        spy = _make_spy_df(close=450, sma_50=440, sma_200=420, atr_14=5.0,
                           sma200_trend=0.05, n_days=250)
        cfg = _default_config()
        sm = _RegimeSmoothing()

        # First few days should be RISK_ON
        for i in range(5):
            plan = classify_regime_at_date(spy, spy.index[200 + i], cfg, smoothing=sm)
        assert plan.regime == Regime.RISK_ON

class TestQQQConfirmation:
    def test_risk_on_with_qqq_confirmation(self):
        spy = _make_spy_df(close=450, sma_50=440, sma_200=420, atr_14=5.0, sma200_trend=0.05)
        qqq = _make_spy_df(close=350, sma_50=340, sma_200=320, atr_14=4.0, sma200_trend=0.05)
        
        cfg = IntelligenceConfig(regime=RegimeConfig(qqq_confirm=True))
        plan = classify_regime_at_date(spy, spy.index[-1], cfg, qqq_df=qqq)
        assert plan.regime == Regime.RISK_ON

    def test_risk_on_blocked_by_weak_qqq(self):
        spy = _make_spy_df(close=450, sma_50=440, sma_200=420, atr_14=5.0, sma200_trend=0.05)
        # QQQ below SMA200
        qqq = _make_spy_df(close=300, sma_50=340, sma_200=320, atr_14=4.0, sma200_trend=0.05)
        
        cfg = IntelligenceConfig(regime=RegimeConfig(qqq_confirm=True))
        plan = classify_regime_at_date(spy, spy.index[-1], cfg, qqq_df=qqq)
        assert plan.regime == Regime.CAUTIOUS

    def test_qqq_confirm_off_ignores_weak_qqq(self):
        spy = _make_spy_df(close=450, sma_50=440, sma_200=420, atr_14=5.0, sma200_trend=0.05)
        # QQQ below SMA200
        qqq = _make_spy_df(close=300, sma_50=340, sma_200=320, atr_14=4.0, sma200_trend=0.05)
        
        cfg = IntelligenceConfig(regime=RegimeConfig(qqq_confirm=False))
        plan = classify_regime_at_date(spy, spy.index[-1], cfg, qqq_df=qqq)
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
