"""Configuration models for the live execution loop."""

from datetime import datetime
from enum import Enum
from typing import List

from pydantic import BaseModel, Field


class ExecutionMode(str, Enum):
    """How the orchestrator handles orders."""
    DRY_RUN = "dry_run"     # Calculate and log everything, do not execute
    MANUAL = "manual"       # Wait for an approval file before executing
    AUTO = "auto"           # Execute all intents immediately


class LiveConfig(BaseModel):
    """Configuration for a single live loop runner."""
    run_id: str
    timeframe: str = "1d"
    universe: List[str] = Field(default_factory=lambda: ["SPY", "QQQ"])
    
    # Engine Settings
    loop_interval_seconds: int = 60
    mode: ExecutionMode = ExecutionMode.DRY_RUN
    
    # Global Risk Limits (Hard Constraints)
    max_positions: int = 5
    max_daily_dd_pct: float = 0.02
    max_heat_pct: float = 0.20
    max_ticker_exposure_pct: float = 0.05
    
    # Runtime Context
    artifact_root: str = "artifacts/live"
    timezone: str = "UTC"


CONSERVATIVE_PROFILE = LiveConfig(
    run_id="conservative_base",
    mode=ExecutionMode.DRY_RUN,
    max_positions=3,
    max_daily_dd_pct=0.015,
    max_heat_pct=0.10,
    max_ticker_exposure_pct=0.04
)

BALANCED_PROFILE = LiveConfig(
    run_id="balanced_base",
    mode=ExecutionMode.DRY_RUN,
    max_positions=5,
    max_daily_dd_pct=0.025,
    max_heat_pct=0.20,
    max_ticker_exposure_pct=0.06
)
