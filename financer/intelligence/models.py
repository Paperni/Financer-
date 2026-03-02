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


class MarketState(BaseModel):
    """The interpreted environmental state from the intelligence engine."""
    regime: Regime = Regime.RISK_ON
    regime_score: float = 0.0           # raw composite (-3.0 to +3.0 currently)
    regime_confidence: float = 0.0      # 0.0–1.0
    narrative: str = ""
    computed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    schema_version: str = "v1"
    features_used: list[str] = Field(default_factory=list)
    source: str = ""

class PolicyOverrides(BaseModel):
    """The derived execution rules dictated by the intelligence engine."""
    max_positions: int = 10
    position_size_multiplier: float = 1.0
    scorecard_threshold: float = 5.0

class ControlPlan(BaseModel):
    """Read-only trading parameter overlay produced by the intelligence engine.

    Consumed by the orchestrator to adjust position sizing, entry thresholds,
    max positions, and sector allowances. The bot works identically without
    a ControlPlan (all values fall back to static config defaults).
    """

    state: MarketState = Field(default_factory=MarketState)
    policy: PolicyOverrides = Field(default_factory=PolicyOverrides)

    # ── Reserved for future intelligence, do not use unless computed ─────────
    event_risk: Optional[str] = None           # e.g., "CLEAR" | "CAUTION" | "HIGH_RISK"
    next_event: Optional[str] = None
    hours_to_event: Optional[float] = None
    sentiment_score: Optional[float] = None    # -1.0 to +1.0
    sentiment_label: Optional[str] = None      # e.g., "FEAR" | "NEUTRAL"
    tier1_sectors: Optional[list[str]] = None
    tier2_sectors: Optional[list[str]] = None
    tier3_sectors: Optional[list[str]] = None
    sector_scores: Optional[dict[str, float]] = None
    allowed_sectors: Optional[list[str]] = None

    # ── Backward Compatibility Proxies ───────────────────────────────────────
    
    @property
    def as_of(self) -> datetime:
        return self.state.computed_at

    @property
    def regime(self) -> Regime:
        return self.state.regime
        
    @property
    def regime_score(self) -> float:
        return self.state.regime_score
        
    @property
    def regime_confidence(self) -> float:
        return self.state.regime_confidence
        
    @property
    def narrative(self) -> str:
        return self.state.narrative

    @property
    def max_positions(self) -> int:
        return self.policy.max_positions

    @property
    def position_size_multiplier(self) -> float:
        return self.policy.position_size_multiplier
        
    @property
    def scorecard_threshold(self) -> float:
        return self.policy.scorecard_threshold

    def __str__(self) -> str:
        return (
            f"REGIME: {self.regime.value} (score: {self.regime_score:+.2f}, "
            f"confidence: {self.regime_confidence:.0%})\n"
            f"NARRATIVE: {self.narrative}\n"
            f"Max Positions: {self.max_positions}  "
            f"Size Mult: {self.position_size_multiplier:.2f}x  "
            f"Threshold: {self.scorecard_threshold}/6"
        )


# ── Factory for neutral / default plans ──────────────────────────────────────

def neutral_plan(as_of: Optional[datetime] = None) -> ControlPlan:
    """Return a ControlPlan with all-neutral defaults."""
    state = MarketState(
        regime=Regime.RISK_ON,
        regime_score=0.0,
        regime_confidence=0.0,
        narrative="Intelligence disabled or unavailable; using static defaults.",
        computed_at=as_of or datetime.now(timezone.utc),
        source="neutral_fallback"
    )
    policy = PolicyOverrides(
        max_positions=10,
        position_size_multiplier=1.0,
        scorecard_threshold=5.0
    )
    return ControlPlan(state=state, policy=policy)
