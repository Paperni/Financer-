"""Risk state models — used by the Risk Governor to gate orders."""

from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, Field

from .enums import Regime


class RiskState(BaseModel):
    """Current risk metrics for the portfolio."""
    regime: Regime = Regime.RISK_ON
    open_risk_pct: float = 0.0          # total $ at risk / equity
    daily_pnl: float = 0.0
    drawdown_pct: float = 0.0
    positions_count: int = 0
    sector_counts: dict[str, int] = Field(default_factory=dict)
    halt_active: bool = False
    halt_reason: str = ""
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class RiskVeto(BaseModel):
    """Result of the Risk Governor evaluating a proposed order."""
    order_id: str
    vetoed: bool
    reason: str = ""
    checks_passed: list[str] = Field(default_factory=list)
    checks_failed: list[str] = Field(default_factory=list)


# ── Regime-aware veto rules (pure functions) ────────────────────────────────

def check_regime_allows_entry(regime: Regime | str | None) -> tuple[bool, str]:
    """Fail-closed: block new entries when regime is unknown or RISK_OFF.

    Returns (allowed, reason).

    Policy:
    - RISK_ON   → entries allowed
    - CAUTIOUS  → entries allowed (reduced size handled by position_size)
    - RISK_OFF  → entries blocked
    - None / unknown → entries blocked (fail-closed)

    Existing positions (stops, exits) are always allowed regardless of
    regime — that logic belongs in the engine/execution layer.
    """
    if regime is None:
        return False, "regime_unknown: fail-closed, no new entries"

    try:
        r = Regime(regime)
    except ValueError:
        return False, f"regime_invalid: '{regime}' is not a valid Regime"

    if r == Regime.RISK_OFF:
        return False, "regime_risk_off: market below SMA-200, no new entries"

    return True, "OK"
