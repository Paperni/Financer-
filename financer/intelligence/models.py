"""Intelligence output models — pure data, no side effects.

The ControlPlan is the single output of the Market Intelligence Engine.
It is read-only: the orchestrator and risk governor consume it but the
intelligence layer never mutates portfolio or engine state.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, Field

from financer.models.enums import Regime


class ControlPlan(BaseModel):
    """Read-only trading parameter overlay produced by the intelligence engine.

    Consumed by the orchestrator to adjust position sizing, entry thresholds,
    max positions, and sector allowances.  The bot works identically without
    a ControlPlan (all values fall back to static config defaults).
    """

    as_of: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    # ── Regime ───────────────────────────────────────────────────────────────
    regime: Regime = Regime.RISK_ON
    regime_score: float = 0.0           # raw composite (-5.0 to +4.0)
    regime_confidence: float = 0.0      # 0.0–1.0, abs(composite) / max

    # ── Sector rankings ──────────────────────────────────────────────────────
    tier1_sectors: list[str] = Field(default_factory=list)  # ETF tickers
    tier2_sectors: list[str] = Field(default_factory=list)
    tier3_sectors: list[str] = Field(default_factory=list)
    sector_scores: dict[str, float] = Field(default_factory=dict)

    # ── Event risk ───────────────────────────────────────────────────────────
    event_risk: str = "CLEAR"           # "CLEAR" | "CAUTION" | "HIGH_RISK"
    next_event: str = ""
    hours_to_event: float = float("inf")

    # ── Sentiment ────────────────────────────────────────────────────────────
    sentiment_score: float = 0.0        # -1.0 to +1.0
    sentiment_label: str = "NEUTRAL"    # "FEAR" | "NEUTRAL" | "GREED"

    # ── Derived trading parameters (THE KEY OUTPUT) ──────────────────────────
    max_positions: int = 10
    position_size_multiplier: float = 1.0
    scorecard_threshold: float = 5.0
    allowed_sectors: list[str] = Field(default_factory=list)

    # ── Narrative ────────────────────────────────────────────────────────────
    narrative: str = ""

    def __str__(self) -> str:
        tier1 = ", ".join(self.tier1_sectors) or "none"
        tier3 = ", ".join(self.tier3_sectors) or "none"
        active = len(self.allowed_sectors)
        return (
            f"REGIME: {self.regime.value} (score: {self.regime_score:+.2f}, "
            f"confidence: {self.regime_confidence:.0%})\n"
            f"EVENT RISK: {self.event_risk}"
            + (f" - {self.next_event} in {self.hours_to_event:.0f}h"
               if self.next_event else "")
            + f"\nSENTIMENT: {self.sentiment_label} ({self.sentiment_score:+.2f})\n"
            f"OVERWEIGHT: {tier1}\n"
            f"UNDERWEIGHT: {tier3}\n"
            f"Max Positions: {self.max_positions}  "
            f"Size Mult: {self.position_size_multiplier:.2f}x  "
            f"Threshold: {self.scorecard_threshold}/6  "
            f"Active Sectors: {active}"
        )


# ── Factory for neutral / default plans ──────────────────────────────────────

def neutral_plan(as_of: Optional[datetime] = None) -> ControlPlan:
    """Return a ControlPlan with all-neutral defaults.

    Used when intelligence is disabled or data is unavailable.
    """
    return ControlPlan(
        as_of=as_of or datetime.now(timezone.utc),
        regime=Regime.RISK_ON,
        regime_score=0.0,
        regime_confidence=0.0,
        event_risk="CLEAR",
        sentiment_score=0.0,
        sentiment_label="NEUTRAL",
        max_positions=10,
        position_size_multiplier=1.0,
        scorecard_threshold=5,
        narrative="Intelligence disabled or unavailable; using static defaults.",
    )
