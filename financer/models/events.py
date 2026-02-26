"""Event flags — cross-engine coordination and runtime control signals."""

from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, Field


class EventFlags(BaseModel):
    """Shared flags that engines and the CIO read to coordinate behavior."""
    earnings_blackout: dict[str, bool] = Field(default_factory=dict)  # ticker -> bool
    regime_change: bool = False
    drawdown_halt: bool = False
    emergency_flatten: bool = False
    pause_buys: bool = False
    pause_sells: bool = False
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
