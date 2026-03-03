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





def _regime_to_params(regime: Regime, params: RegimeParamsConfig) -> dict:
    """Look up trading parameters for a given regime."""
    if regime == Regime.RISK_ON:
        return {
            "allow_entries": True,
            "max_positions": params.risk_on_max_positions,
            "position_size_multiplier": params.risk_on_size_mult,
            "scorecard_threshold": params.risk_on_threshold,
        }
    if regime == Regime.RISK_OFF:
        return {
            "allow_entries": False,
            "max_positions": params.risk_off_max_positions,
            "position_size_multiplier": params.risk_off_size_mult,
            "scorecard_threshold": params.risk_off_threshold,
        }
    # CAUTIOUS
    return {
        "allow_entries": True,
        "max_positions": params.cautious_max_positions,
        "position_size_multiplier": params.cautious_size_mult,
        "scorecard_threshold": params.cautious_threshold,
    }


# ── Smoothing state ──────────────────────────────────────────────────────────

class _RegimeSmoothing:
    """Track consecutive confirmations to prevent whipsaw regime changes.

    Not persisted across runs — each backtest starts fresh.
    """

    def __init__(self):
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

        # Determine target threshold
        target_days = 2  # default (e.g. CAUTIOUS)
        if raw_regime == Regime.RISK_ON:
            target_days = 3
        elif raw_regime == Regime.RISK_OFF:
            target_days = 2

        if self._pending_count >= target_days:
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
    qqq_df: Optional[pd.DataFrame] = None,
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
    qqq_df : pd.DataFrame, optional
        QQQ feature DataFrame for double confirmation if config.regime.qqq_confirm is True.

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
    slope_pct = 0.0
    if sma200_col is not None and len(sma200_col) >= regime_cfg.sma200_slope_lookback + 1:
        current_sma = sma200_col.iloc[-1]
        past_sma = sma200_col.iloc[-(regime_cfg.sma200_slope_lookback + 1)]
        if not pd.isna(current_sma) and not pd.isna(past_sma) and past_sma != 0:
            slope_pct = (current_sma - past_sma) / past_sma
            
    atr_pct = atr / close if (not pd.isna(atr) and close > 0) else 0.0

    # Strict Boolean Hierarchy for SPY
    is_risk_off = False
    is_risk_on = False

    if (close < sma200) or (atr_pct > regime_cfg.atr_vol_threshold) or (slope_pct < -regime_cfg.sma200_slope_threshold):
        is_risk_off = True
    elif (close > sma50 and close > sma200) and (atr_pct < regime_cfg.atr_vol_threshold) and (slope_pct > regime_cfg.sma200_slope_threshold):
        is_risk_on = True

    # QQQ Confirmation
    if is_risk_on and regime_cfg.qqq_confirm:
        if qqq_df is not None and not qqq_df.empty:
            q_sliced = qqq_df.loc[:dt]
            if not q_sliced.empty and "close" in q_sliced.columns:
                q_row = q_sliced.iloc[-1]
                q_close = float(q_row.get("close", 0.0))
                q_sma50 = float(q_row.get("sma_50", float("nan")))
                q_sma200 = float(q_row.get("sma_200", float("nan")))
                q_atr = float(q_row.get("atr_14", float("nan")))
                
                q_slope_pct = 0.0
                q_sma200_col = q_sliced.get("sma_200")
                if q_sma200_col is not None and len(q_sma200_col) >= regime_cfg.sma200_slope_lookback + 1:
                    q_cur_sma = q_sma200_col.iloc[-1]
                    q_past_sma = q_sma200_col.iloc[-(regime_cfg.sma200_slope_lookback + 1)]
                    if not pd.isna(q_cur_sma) and not pd.isna(q_past_sma) and q_past_sma != 0:
                        q_slope_pct = (q_cur_sma - q_past_sma) / q_past_sma
                
                q_atr_pct = q_atr / q_close if (not pd.isna(q_atr) and q_close > 0) else 0.0
                
                # Check if QQQ is in RISK_ON
                q_is_risk_on = (q_close > q_sma50 and q_close > q_sma200) and (q_atr_pct < regime_cfg.atr_vol_threshold) and (q_slope_pct > regime_cfg.sma200_slope_threshold)
                
                if not q_is_risk_on:
                    is_risk_on = False
            else:
                is_risk_on = False
        else:
            is_risk_on = False

    if is_risk_off:
        raw_regime = Regime.RISK_OFF
    elif is_risk_on:
        raw_regime = Regime.RISK_ON
    else:
        raw_regime = Regime.CAUTIOUS

    # Apply smoothing if provided
    regime = smoothing.update(raw_regime) if smoothing else raw_regime

    # Map to trading parameters
    trading_params = _regime_to_params(regime, params_cfg)
    confidence = 1.0  # Simplistic boolean confidence

    narrative = (
        f"Regime {regime.value}: close={close:.1f}, "
        f"sma50={sma50:.1f}, sma200={sma200:.1f}, "
        f"atr%={atr_pct:.1%}, sma200_slope={slope_pct:.1%}"
    )

    state = MarketState(
        regime=regime,
        regime_score=0.0,
        regime_confidence=min(confidence, 1.0),
        narrative=narrative,
        computed_at=dt.to_pydatetime(),
        source="intelligence.regime_classifier"
    )
    
    # Enforce Clamps
    raw_max_pos = trading_params["max_positions"]
    clamped_max_pos = min(raw_max_pos, params_cfg.risk_on_max_positions)
    
    raw_size_mult = trading_params["position_size_multiplier"]
    clamped_size_mult = max(0.0, min(1.0, raw_size_mult))
    
    raw_threshold = trading_params["scorecard_threshold"]
    clamped_threshold = max(4.0, min(6.0, raw_threshold))

    policy = PolicyOverrides(
        allow_entries=trading_params["allow_entries"],
        max_positions=clamped_max_pos,
        position_size_multiplier=clamped_size_mult,
        scorecard_threshold=clamped_threshold
    )

    return ControlPlan(state=state, policy=policy)
