"""Price-based regime classifier (v1) — SPY-only signals.

Classifies the market into RISK_ON / CAUTIOUS / RISK_OFF using three
price-derived signals.  Returns a ControlPlan with derived trading
parameters (max positions, size multiplier, score threshold).

No VIX, no FRED, no breadth — pure price action.  Additional signals
will be layered in future phases.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

import pandas as pd

from financer.models.enums import Regime

from .config import IntelligenceConfig, RegimeConfig, RegimeParamsConfig
from .models import ControlPlan, MarketState, PolicyOverrides, neutral_plan

logger = logging.getLogger(__name__)


# ── Signal functions (pure, no side effects) ─────────────────────────────────

def _sma_structure_signal(
    close: float,
    sma50: float,
    sma200: float,
) -> float:
    """Score SMA structure: +1 bullish, 0 neutral, -1 bearish."""
    if pd.isna(close) or pd.isna(sma200):
        return 0.0
    if close < sma200:
        return -1.0
    if pd.isna(sma50) or close < sma50:
        return 0.0  # between SMA-200 and SMA-50 = neutral
    return 1.0  # above both


def _sma200_slope_signal(
    sma200_series: pd.Series,
    lookback: int,
    threshold: float,
) -> float:
    """Score SMA-200 slope: +1 rising, 0 flat, -1 falling."""
    if len(sma200_series) < lookback + 1:
        return 0.0
    current = sma200_series.iloc[-1]
    past = sma200_series.iloc[-(lookback + 1)]
    if pd.isna(current) or pd.isna(past) or past == 0:
        return 0.0
    slope_pct = (current - past) / past
    if slope_pct > threshold:
        return 1.0
    if slope_pct < -threshold:
        return -1.0
    return 0.0


def _atr_volatility_signal(
    atr: float,
    close: float,
    vol_threshold: float,
) -> float:
    """Score ATR% volatility: +1 low vol, 0 normal, -1 high vol."""
    if pd.isna(atr) or pd.isna(close) or close <= 0:
        return 0.0
    atr_pct = atr / close
    if atr_pct > vol_threshold:
        return -1.0
    if atr_pct < vol_threshold * 0.5:
        return 1.0
    return 0.0


# ── Composite classification ─────────────────────────────────────────────────

def _composite_to_regime(composite: float) -> Regime:
    """Map composite score to Regime enum.

    Range: -3.0 to +3.0
      >= +2  -> RISK_ON
      <= -1  -> RISK_OFF
      else   -> CAUTIOUS
    """
    if composite >= 2.0:
        return Regime.RISK_ON
    if composite <= -1.0:
        return Regime.RISK_OFF
    return Regime.CAUTIOUS


def _regime_to_params(regime: Regime, params: RegimeParamsConfig) -> dict:
    """Look up trading parameters for a given regime."""
    if regime == Regime.RISK_ON:
        return {
            "max_positions": params.risk_on_max_positions,
            "position_size_multiplier": params.risk_on_size_mult,
            "scorecard_threshold": params.risk_on_threshold,
        }
    if regime == Regime.RISK_OFF:
        return {
            "max_positions": params.risk_off_max_positions,
            "position_size_multiplier": params.risk_off_size_mult,
            "scorecard_threshold": params.risk_off_threshold,
        }
    # CAUTIOUS
    return {
        "max_positions": params.cautious_max_positions,
        "position_size_multiplier": params.cautious_size_mult,
        "scorecard_threshold": params.cautious_threshold,
    }


# ── Smoothing state ──────────────────────────────────────────────────────────

class _RegimeSmoothing:
    """Track consecutive confirmations to prevent whipsaw regime changes.

    Not persisted across runs — each backtest starts fresh.
    """

    def __init__(self, confirmation_days: int = 2):
        self.confirmation_days = confirmation_days
        self._confirmed_regime: Regime = Regime.RISK_ON
        self._pending_regime: Optional[Regime] = None
        self._pending_count: int = 0

    def update(self, raw_regime: Regime) -> Regime:
        """Apply smoothing and return the confirmed regime."""
        if raw_regime == self._confirmed_regime:
            # Signal agrees with current — reset any pending transition
            self._pending_regime = None
            self._pending_count = 0
            return self._confirmed_regime

        # Signal disagrees — count consecutive confirmations
        if raw_regime == self._pending_regime:
            self._pending_count += 1
        else:
            self._pending_regime = raw_regime
            self._pending_count = 1

        if self._pending_count >= self.confirmation_days:
            self._confirmed_regime = raw_regime
            self._pending_regime = None
            self._pending_count = 0

        return self._confirmed_regime


# ── Public API ────────────────────────────────────────────────────────────────

def classify_regime_at_date(
    spy_df: pd.DataFrame,
    date: datetime | pd.Timestamp,
    config: IntelligenceConfig,
    smoothing: Optional[_RegimeSmoothing] = None,
) -> ControlPlan:
    """Classify market regime as-of *date* and return a ControlPlan.

    Parameters
    ----------
    spy_df : pd.DataFrame
        SPY feature DataFrame with columns: close, sma_50, sma_200, atr_14.
        Index must be a DatetimeIndex.
    date : datetime or pd.Timestamp
        Classification date.  Only data up to and including this date is used
        (no lookahead).
    config : IntelligenceConfig
        Full intelligence config (uses ``config.regime`` and ``config.regime_params``).
    smoothing : _RegimeSmoothing, optional
        Smoothing state tracker.  If None, raw regime is used without smoothing.
        Callers running day-by-day backtests should pass a persistent instance.

    Returns
    -------
    ControlPlan
        With regime, trading parameters, and narrative populated.
    """
    regime_cfg = config.regime
    params_cfg = config.regime_params

    # Normalize date for slicing
    dt = pd.Timestamp(date)
    if dt.tzinfo is None:
        dt = dt.tz_localize("UTC")
    else:
        dt = dt.tz_convert("UTC")

    # Slice up to date — no lookahead
    sliced = spy_df.loc[:dt]

    if sliced.empty or "close" not in sliced.columns:
        logger.warning("No SPY data up to %s; returning neutral plan", date)
        return neutral_plan(as_of=dt.to_pydatetime())

    row = sliced.iloc[-1]
    close = float(row.get("close", 0.0))

    if close <= 0 or pd.isna(close):
        return neutral_plan(as_of=dt.to_pydatetime())

    # Compute SMA values from the sliced data
    sma50 = float(row.get("sma_50", float("nan")))
    sma200 = float(row.get("sma_200", float("nan")))
    atr = float(row.get("atr_14", float("nan")))

    # Build SMA-200 series for slope calculation
    sma200_col = sliced.get("sma_200")
    if sma200_col is None:
        sma200_col = pd.Series(dtype=float)

    # Signal 1: SMA structure
    sig_structure = _sma_structure_signal(close, sma50, sma200)

    # Signal 2: SMA-200 slope
    sig_slope = _sma200_slope_signal(
        sma200_col,
        lookback=regime_cfg.sma200_slope_lookback,
        threshold=regime_cfg.sma200_slope_threshold,
    )

    # Signal 3: ATR% volatility
    sig_vol = _atr_volatility_signal(atr, close, regime_cfg.atr_vol_threshold)

    # Composite
    composite = sig_structure + sig_slope + sig_vol
    raw_regime = _composite_to_regime(composite)

    shock_narrative = ""
    # Signal 4: Trailing Volatility Shock Override
    if len(sliced) > 0:
        lookback_slice = sliced.iloc[-regime_cfg.vol_shock_lookback:]
        # Compute daily ATR%
        atr_pct_series = lookback_slice["atr_14"] / lookback_slice["close"]
        vol_shock = atr_pct_series.max()
        
        if vol_shock > regime_cfg.vol_shock_risk_off_threshold:
            raw_regime = Regime.RISK_OFF
            shock_narrative = f" [SHOCK: RISK_OFF (max_atr={vol_shock:.1%})]"
        elif vol_shock > regime_cfg.vol_shock_cautious_threshold:
            raw_regime = Regime.CAUTIOUS
            shock_narrative = f" [SHOCK: CAUTIOUS (max_atr={vol_shock:.1%})]"

    # Apply smoothing if provided
    regime = smoothing.update(raw_regime) if smoothing else raw_regime

    # Map to trading parameters
    trading_params = _regime_to_params(regime, params_cfg)
    confidence = abs(composite) / 3.0  # normalize to 0–1

    narrative = (
        f"Regime {regime.value}: structure={sig_structure:+.0f}, "
        f"slope={sig_slope:+.0f}, vol={sig_vol:+.0f} "
        f"(composite={composite:+.1f}){shock_narrative}"
    )

    state = MarketState(
        regime=regime,
        regime_score=composite,
        regime_confidence=min(confidence, 1.0),
        narrative=narrative,
        computed_at=dt.to_pydatetime(),
        source="intelligence.regime_classifier"
    )
    
    policy = PolicyOverrides(
        max_positions=trading_params["max_positions"],
        position_size_multiplier=trading_params["position_size_multiplier"],
        scorecard_threshold=trading_params["scorecard_threshold"]
    )

    return ControlPlan(state=state, policy=policy)
