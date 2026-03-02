"""RiskScore framework — continuous 0–100 regime scoring with hysteresis.

Replaces the discrete 3-signal composite with a continuous risk score and
adds hysteresis-based regime transitions to prevent whipsaw while enabling
faster re-entry via a "fast lane" signal.

Designed to be wired into the replay/live loop in a future prompt.
Breadth sub-score is wired to the breadth proxy; vol sub-score is
still a stub returning neutral (50).
"""

from __future__ import annotations

import logging
from typing import Optional

import pandas as pd

from financer.models.enums import Regime

logger = logging.getLogger(__name__)


# ── Sub-score functions ──────────────────────────────────────────────────────

def compute_trend_score(spy_features: pd.DataFrame) -> float:
    """Compute a trend sub-score from SPY price data (0–100).

    Components (equally weighted):
    - SMA structure: close vs SMA-50 vs SMA-200
    - SMA-200 slope: 20-day pct change of SMA-200
    - SMA-50 slope: 20-day pct change of SMA-50

    Parameters
    ----------
    spy_features : pd.DataFrame
        Must contain columns: close, sma_50, sma_200.
        Should have at least 21 rows for slope calculation.

    Returns
    -------
    float
        Score from 0.0 (strongly bearish) to 100.0 (strongly bullish).
        Returns 50.0 (neutral) if data is insufficient or invalid.
    """
    if spy_features.empty or len(spy_features) < 2:
        return 50.0

    for col in ("close", "sma_50", "sma_200"):
        if col not in spy_features.columns:
            return 50.0

    row = spy_features.iloc[-1]
    close = float(row["close"])
    sma50 = float(row["sma_50"])
    sma200 = float(row["sma_200"])

    if pd.isna(close) or close <= 0:
        return 50.0

    # Component 1: SMA structure (0–100)
    if pd.isna(sma200):
        structure_score = 50.0
    elif close < sma200:
        # Below SMA-200: map distance as penalty (0–40)
        pct_below = (sma200 - close) / sma200
        structure_score = max(0.0, 40.0 - pct_below * 500.0)
    elif pd.isna(sma50) or close < sma50:
        # Between SMA-200 and SMA-50: 40–70
        if pd.isna(sma50) or sma50 == sma200:
            structure_score = 55.0
        else:
            pct_range = (close - sma200) / (sma50 - sma200) if sma50 > sma200 else 0.5
            structure_score = 40.0 + min(pct_range, 1.0) * 30.0
    else:
        # Above both: 70–100
        pct_above = (close - sma50) / sma50 if sma50 > 0 else 0.0
        structure_score = 70.0 + min(pct_above * 300.0, 30.0)

    # Component 2: SMA-200 slope (0–100)
    lookback = 20
    sma200_slope_score = 50.0
    if len(spy_features) >= lookback + 1:
        sma200_series = spy_features["sma_200"]
        current = sma200_series.iloc[-1]
        past = sma200_series.iloc[-(lookback + 1)]
        if not pd.isna(current) and not pd.isna(past) and past > 0:
            slope_pct = (current - past) / past
            # Map slope to 0–100: -2% -> 0, 0% -> 50, +2% -> 100
            sma200_slope_score = max(0.0, min(100.0, 50.0 + slope_pct * 2500.0))

    # Component 3: SMA-50 slope (0–100)
    sma50_slope_score = 50.0
    if len(spy_features) >= lookback + 1:
        sma50_series = spy_features["sma_50"]
        current = sma50_series.iloc[-1]
        past = sma50_series.iloc[-(lookback + 1)]
        if not pd.isna(current) and not pd.isna(past) and past > 0:
            slope_pct = (current - past) / past
            # SMA-50 is noisier, use narrower range: -3% -> 0, +3% -> 100
            sma50_slope_score = max(0.0, min(100.0, 50.0 + slope_pct * 1666.7))

    # Equal weight average
    trend_score = (structure_score + sma200_slope_score + sma50_slope_score) / 3.0
    return max(0.0, min(100.0, trend_score))


def compute_breadth_score(breadth_pct: float = 50.0) -> float:
    """Map breadth percentage to a sub-score (0–100).

    Currently an identity mapping with clamping.  A non-linear transform
    (e.g. sigmoid around 50%) can be layered later without changing callers.

    Parameters
    ----------
    breadth_pct : float
        Percentage of universe above SMA-200 (0–100).
        Default 50.0 (neutral) when breadth data is unavailable.

    Returns
    -------
    float
        Breadth sub-score clamped to [0, 100].
    """
    return max(0.0, min(100.0, breadth_pct))


def compute_vol_score() -> float:
    """Stub: volatility sub-score (0–100). Returns neutral until data wired."""
    return 50.0


def compute_risk_score(
    trend_score: float,
    breadth_score: float = 50.0,
    vol_score: float = 50.0,
) -> float:
    """Combine sub-scores into a single risk score (0–100).

    Current weighting (will evolve as data sources are wired):
    - Trend: 60%
    - Breadth: 20% (stub)
    - Vol: 20% (stub)

    Parameters
    ----------
    trend_score : float
        Trend sub-score (0–100).
    breadth_score : float
        Breadth sub-score (0–100). Default 50.0 (neutral stub).
    vol_score : float
        Volatility sub-score (0–100). Default 50.0 (neutral stub).

    Returns
    -------
    float
        Composite risk score from 0.0 (maximum risk-off) to 100.0 (maximum risk-on).
    """
    score = (
        trend_score * 0.60
        + breadth_score * 0.20
        + vol_score * 0.20
    )
    return max(0.0, min(100.0, score))


# ── Fast-lane signal ────────────────────────────────────────────────────────

def compute_fast_lane_signal(
    spy_features: pd.DataFrame,
    n_days: int = 5,
    breadth_pct: float | None = None,
    breadth_threshold: float = 45.0,
) -> bool:
    """Detect a fast-lane re-entry signal.

    The fast lane activates when:
    1. SPY close > SMA-50 for *n_days* consecutive trading days, AND
    2. SMA-50 slope over those days is positive (last > first), AND
    3. breadth_pct > breadth_threshold (if breadth_pct is provided).

    This allows faster transition from RISK_OFF/CAUTIOUS → RISK_ON
    without waiting for the full hysteresis confirmation.

    Parameters
    ----------
    spy_features : pd.DataFrame
        Must contain columns: close, sma_50. Needs at least *n_days* rows.
    n_days : int
        Number of consecutive days required. Default 5.
    breadth_pct : float or None
        Universe breadth percentage.  When provided, must exceed
        *breadth_threshold* for the fast lane to activate.
        When None, the breadth gate is skipped (backward compat).
    breadth_threshold : float
        Minimum breadth_pct required to activate fast lane. Default 45.0.

    Returns
    -------
    bool
        True if fast-lane conditions are met.
    """
    if spy_features.empty or len(spy_features) < n_days:
        return False

    for col in ("close", "sma_50"):
        if col not in spy_features.columns:
            return False

    tail = spy_features.iloc[-n_days:]

    close_vals = tail["close"]
    sma50_vals = tail["sma_50"]

    # Check for any NaN in the window
    if close_vals.isna().any() or sma50_vals.isna().any():
        return False

    # Condition 1: close > sma_50 for all n_days
    if not (close_vals > sma50_vals).all():
        return False

    # Condition 2: SMA-50 slope positive over the window
    sma50_first = float(sma50_vals.iloc[0])
    sma50_last = float(sma50_vals.iloc[-1])
    if sma50_first <= 0 or sma50_last <= sma50_first:
        return False

    # Condition 3: breadth gate (when provided)
    if breadth_pct is not None and breadth_pct <= breadth_threshold:
        return False

    return True


# ── Fast-lane hysteresis ───────────────────────────────────────────────────

_FL_BREADTH_ENTER = 45.0  # breadth must exceed this to activate fast lane
_FL_BREADTH_EXIT = 38.0   # breadth must fall below this to deactivate


def compute_fast_lane_with_hysteresis(
    spy_features: pd.DataFrame,
    breadth_pct: float,
    prev_fast_lane: bool = False,
    n_days: int = 5,
) -> bool:
    """Fast-lane signal with breadth hysteresis.

    Once the fast lane is active it remains active until breadth drops
    below ``_FL_BREADTH_EXIT`` (38%) *or* the SPY/slope conditions fail.
    This prevents the fast lane from flickering on/off around the 45%
    activation threshold.

    Parameters
    ----------
    spy_features : pd.DataFrame
        Must contain columns: close, sma_50.
    breadth_pct : float
        Current universe breadth percentage (0–100).
    prev_fast_lane : bool
        Whether the fast lane was active on the previous bar.
    n_days : int
        Consecutive days for SPY > SMA-50.

    Returns
    -------
    bool
        Whether the fast lane is active.
    """
    # Check SPY/slope conditions (without breadth gate — we handle it here)
    spy_ok = compute_fast_lane_signal(spy_features, n_days=n_days)

    if not spy_ok:
        return False

    if prev_fast_lane:
        # Stay active unless breadth drops below exit threshold
        return breadth_pct >= _FL_BREADTH_EXIT
    else:
        # Activate only if breadth exceeds entry threshold
        return breadth_pct > _FL_BREADTH_ENTER


# ── Hysteresis regime classifier ────────────────────────────────────────────

# Thresholds for regime transitions (asymmetric for hysteresis)
_RISK_ON_ENTER = 65.0   # score must rise above this to enter RISK_ON
_RISK_ON_EXIT = 55.0    # score must fall below this to leave RISK_ON
_RISK_OFF_ENTER = 35.0  # score must fall below this to enter RISK_OFF
_RISK_OFF_EXIT = 45.0   # score must rise above this to leave RISK_OFF


def classify_regime_with_hysteresis(
    risk_score: float,
    prev_regime: Regime,
    fast_lane: bool = False,
) -> Regime:
    """Classify regime using asymmetric thresholds to prevent whipsaw.

    The hysteresis bands create "dead zones" where the regime stays unchanged:
    - RISK_ON requires score >= 65 to enter, but only exits below 55
    - RISK_OFF requires score <= 35 to enter, but only exits above 45
    - CAUTIOUS is the default in between

    The fast_lane flag bypasses the RISK_ON entry threshold, allowing
    re-entry at the lower exit threshold (55) when the fast-lane signal
    is active.

    Parameters
    ----------
    risk_score : float
        Composite risk score (0–100).
    prev_regime : Regime
        Previous regime state (for hysteresis).
    fast_lane : bool
        If True, lowers the RISK_ON entry threshold to the exit threshold.

    Returns
    -------
    Regime
        The classified regime.
    """
    risk_on_threshold = _RISK_ON_EXIT if fast_lane else _RISK_ON_ENTER

    if prev_regime == Regime.RISK_ON:
        if risk_score < _RISK_ON_EXIT:
            if risk_score <= _RISK_OFF_ENTER:
                return Regime.RISK_OFF
            return Regime.CAUTIOUS
        return Regime.RISK_ON

    if prev_regime == Regime.RISK_OFF:
        if risk_score > _RISK_OFF_EXIT:
            if risk_score >= risk_on_threshold:
                return Regime.RISK_ON
            return Regime.CAUTIOUS
        return Regime.RISK_OFF

    # prev_regime == CAUTIOUS
    if risk_score >= risk_on_threshold:
        return Regime.RISK_ON
    if risk_score <= _RISK_OFF_ENTER:
        return Regime.RISK_OFF
    return Regime.CAUTIOUS
