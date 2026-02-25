"""Allocation policy for the Swing Engine based on market regimes."""

from __future__ import annotations

from financer.models.enums import EngineSource, Regime
from financer.models.intents import AllocationIntent, ReasonCode


def determine_allocation(regime: Regime) -> AllocationIntent:
    """Determine the broad portfolio allocation based on the market regime."""
    reasons = []

    if regime == Regime.RISK_ON:
        cash_pct = 0.0
        baseline_pct = 0.20
        swing_pct = 0.80
        reasons.append(
            ReasonCode(
                code="REGIME_RISK_ON",
                weight=1.0,
                detail="Market is in a structural uptrend. Maximum swing allocation."
            )
        )
    elif regime == Regime.CAUTIOUS:
        cash_pct = 0.40
        baseline_pct = 0.30
        swing_pct = 0.30
        reasons.append(
            ReasonCode(
                code="REGIME_CAUTIOUS",
                weight=1.0,
                detail="Market momentum is fading. Reduced swing allocation and heavier cash."
            )
        )
    else:  # Regime.RISK_OFF
        cash_pct = 0.80
        baseline_pct = 0.20
        swing_pct = 0.0
        reasons.append(
            ReasonCode(
                code="REGIME_RISK_OFF",
                weight=1.0,
                detail="Market is in a structural downtrend. Capital preservation mode."
            )
        )

    return AllocationIntent(
        source=EngineSource.SWING,
        cash_pct=cash_pct,
        baseline_pct=baseline_pct,
        swing_pct=swing_pct,
        regime=regime,
        reasons=reasons,
    )
